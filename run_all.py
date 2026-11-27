"""准备数据并独立运行 Q1–Q4；Q4 默认只验证分流，不调用付费 API。"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent
RETAIL_DATASET = "mashlyn/online-retail-ii-uci"
OLIST_DATASET = "olistbr/brazilian-ecommerce"
OLIST_FILES = (
    "olist_customers_dataset.csv",
    "olist_geolocation_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
)
MODULES = {
    "q1": ("retail", "q1_data_quality/q1_code.py", ()),
    "q2": ("olist", "q2_sql_analysis/import_olist.py", ("--run-queries", "--non-interactive")),
    "q3": ("retail", "q3_etl_pipeline/pipeline.py", ()),
    "q4": ("olist", "q4_llm_extraction/extract_reviews.py", ()),
}


def is_ready(path: Path) -> bool:
    """只有存在且非空的 CSV 才能复用。"""
    return path.is_file() and path.stat().st_size > 0


def copy_csv(source: Path, destination: Path) -> None:
    """复制完成后再替换目标，避免中途中断留下不完整的 CSV。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as temporary:
        staging_path = Path(temporary.name)
    try:
        shutil.copyfile(source, staging_path)
        if staging_path.stat().st_size != source.stat().st_size:
            raise OSError(f"复制后的文件大小不一致：{destination}")
        staging_path.replace(destination)
    finally:
        staging_path.unlink(missing_ok=True)


def prepare_dataset(dataset_id: str, required_files: dict[str, Path]) -> None:
    """下载缺失数据，并检查 Kaggle 返回的目录包含所需文件。"""
    missing = {name: path for name, path in required_files.items() if not is_ready(path)}
    if not missing:
        LOGGER.info("复用本地数据：%s", dataset_id)
        return

    import kagglehub

    LOGGER.info("准备数据集 %s，需补齐 %d 个 CSV", dataset_id, len(missing))
    cache_dir = Path(kagglehub.dataset_download(dataset_id))
    cached_files = {path.name.casefold(): path for path in cache_dir.iterdir() if path.is_file()}

    unavailable = [name for name in missing
                   if name.casefold() not in cached_files or not is_ready(cached_files[name.casefold()])]
    if unavailable:
        raise FileNotFoundError(f"数据集 {dataset_id} 缺少非空文件：{', '.join(unavailable)}")

    for name, destination in missing.items():
        copy_csv(cached_files[name.casefold()], destination)
        LOGGER.info("已准备 %s", destination)


def data_sources(data_dir: Path) -> dict:
    return {
        "retail": (RETAIL_DATASET, {"online_retail_II.csv": data_dir / "online_retail_ii.csv"}),
        "olist": (OLIST_DATASET, {name: data_dir / "olist" / name for name in OLIST_FILES}),
    }


def prepare_data(data_dir: Path) -> None:
    """准备题目要求的一个 Retail CSV 和九个 Olist CSV。"""
    for dataset, files in data_sources(data_dir).values():
        prepare_dataset(dataset, files)


def run_modules(
    modules: tuple[str, ...], *, q4_mode: str = "dry-run", q4_limit: int = 0,
    timeout: int = 2400,
) -> int:
    """按依赖准备数据，隔离模块失败并返回整体状态。"""
    started = perf_counter()
    prepared = {}
    for name, (dataset, files) in data_sources(PROJECT_ROOT / "data").items():
        if not any(MODULES[module][0] == name for module in modules):
            continue
        try:
            prepare_dataset(dataset, files)
            prepared[name] = True
        except Exception:
            prepared[name] = False
            LOGGER.exception("数据准备失败：%s", name)

    results = {}
    for module in modules:
        source, relative_path, arguments = MODULES[module]
        script = PROJECT_ROOT / relative_path
        log_path = PROJECT_ROOT / f"run_all_{module}.log"
        result = {"status": "failed", "returncode": None, "elapsed_seconds": 0.0,
                  "log": log_path.name, "detail": ""}
        results[module] = result
        if not script.is_file():
            result.update(status="missing_entry", detail=f"缺少入口 {relative_path}")
            log_path.write_text(result["detail"] + "\n", encoding="utf-8")
            continue
        if not prepared[source]:
            result.update(status="data_unavailable", detail=f"依赖的数据准备失败（{source}）")
            log_path.write_text(result["detail"] + "\n", encoding="utf-8")
            continue

        if module == "q4":
            arguments = (*arguments, "--input", str(PROJECT_ROOT / "data" / "olist"
                         / "olist_order_reviews_dataset.csv"))
            if q4_mode == "dry-run":
                arguments += ("--dry-run",)
            if q4_limit:
                arguments += ("--limit", str(q4_limit))
        module_started = perf_counter()
        try:
            LOGGER.info("开始 %s，日志 %s", module.upper(), log_path.name)
            with log_path.open("w", encoding="utf-8") as log:
                subprocess.run(
                    [sys.executable, "-B", "-X", "utf8", str(script), *arguments],
                    cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, check=True,
                    timeout=timeout,
                )
        except subprocess.TimeoutExpired:
            result.update(status="timeout", detail=f"超过单模块时限 {timeout} 秒")
        except (OSError, subprocess.CalledProcessError) as error:
            result.update(returncode=getattr(error, "returncode", None), detail=str(error))
        else:
            dry_run = module == "q4" and q4_mode == "dry-run"
            result.update(status="validated" if dry_run else "success", returncode=0,
                          detail="仅完成数据读取与分流验证，未调用 LLM" if dry_run else "执行完成")
        finally:
            result["elapsed_seconds"] = round(perf_counter() - module_started, 3)

    labels = {"success": "成功", "validated": "分流验证通过（dry-run）", "failed": "失败",
              "timeout": "超时", "missing_entry": "缺少入口", "data_unavailable": "数据未就绪"}
    for module, result in results.items():
        LOGGER.info("%s %s，耗时 %.3f 秒；%s；日志 %s", module.upper(), labels[result["status"]],
                    result["elapsed_seconds"], result["detail"], result["log"])
    success = all(result["status"] in {"success", "validated"} for result in results.values())
    summary_path = PROJECT_ROOT / "run_all_summary.json"
    summary_path.write_text(json.dumps({
        "python": sys.executable, "q4_mode": q4_mode,
        "elapsed_seconds": round(perf_counter() - started, 3),
        "data_ready": prepared, "modules": results, "exit_code": 0 if success else 1,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOGGER.info("运行汇总：%s", summary_path)
    return 0 if success else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="自动准备数据并运行 Q1–Q4")
    parser.add_argument("--modules", choices=tuple(MODULES), nargs="+", default=list(MODULES),
                        help="默认运行全部，也可指定一个或多个模块")
    parser.add_argument("--q4-mode", choices=("dry-run", "live"), default="dry-run",
                        help="Q4 默认只验证分流；live 才实际调用 API，需要密钥和可用预算")
    parser.add_argument("--q4-limit", type=int, default=0, help="Q4 处理条数，0 表示全部符合条件的评价")
    parser.add_argument("--timeout", type=int, default=2400, help="单模块超时秒数，默认 40 分钟")
    args = parser.parse_args()
    if args.q4_limit < 0 or args.timeout <= 0:
        parser.error("--q4-limit 不能为负数，--timeout 必须大于 0")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    modules = tuple(module for module in MODULES if module in args.modules)
    LOGGER.info("Python：%s", sys.executable)
    return run_modules(modules, q4_mode=args.q4_mode, q4_limit=args.q4_limit, timeout=args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
