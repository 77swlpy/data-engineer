''' 题目提示后我的想法'''
#如果多笔正向销售符合条件，匹配哪一笔？匹配最近的一笔
#如果客户买了 10 个、分两次退货各退 5 个怎么办？通过用户ID进行匹配，先选取所有退货快递进行比对，如果没有一次性符合的内容，则选取最近的一笔商品id相同的进行比对然后是次近的
#如果原单的 quantity 比退货的小怎么办？记为异常单
#上两条可，后面3太草率了，继续查次近的候选。如果有一笔更早的销售足够，按规则匹配。如果没有任何单笔足够，但多笔加起来足够，记为「可能跨原单」。如果所有可用历史销售加起来也不足，记为「历史可退数量不足」。后两种都留 NULL。（ai探讨给出）
#新问题：等量优先也可能匹配错原单。 假设客户先买了 5 件，后来又买了 10 件，然后退 5 件。按「等量优先」会匹配较早的 5 件单，但这 5 件也可能是从较新的 10 件单中退回的。
#ai问题：哪怕上文已经明确需要分类，但是对细节进行追问的时候还是会出现混淆，这个时候需要人工纠错。


import argparse
import logging
import random
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np
import pandas as pd


LOGGER = logging.getLogger(__name__)
SEED = 42
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIELDS = {
    "Invoice": "invoice_no",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "Price": "unit_price",
    "InvoiceDate": "invoice_datetime",
    "Customer ID": "customer_id",
    "Country": "country",
}
FACT_COLUMNS = [
    "invoice_no", "stock_code", "description", "quantity", "unit_price",
    "total_amount", "invoice_datetime", "customer_id", "country",
]
CUSTOMER_COLUMNS = [
    "customer_id", "recency_days", "frequency", "monetary", "first_purchase_date",
    "last_purchase_date", "unique_products", "country", "is_one_time_buyer",
]
RETURN_COLUMNS = FACT_COLUMNS + ["matched_original_invoice"]
NON_PRODUCT_CODES = {
    "POST", "DOT", "BANK CHARGES", "AMAZONFEE", "CRUK", "D", "ADJUST", "B", "M", "S",
}
# Q1.2 查看过商品明细的特殊格式编码，并保留原始编码的大小写。
VERIFIED_NAMES = {
    "PADS": "PADS TO MATCH ALL CUSHIONS",
    "DCGSSBOY": "BOYS PARTY BAG",
    "DCGSSGIRL": "GIRLS PARTY BAG",
    "DCGS0003": "BOXED GLASS ASHTRAY",
    "20713": "JUMBO BAG OWLS",
}
BUSINESS_NOTES = r"(?:found|missing|update|ebay|wrongly (?:coded|marked)\b.*|marked as\b.*)"
MATCHED = ("等量匹配", "部分退货推断")


def run_step(name, function, *args):
    """为每个阶段统一记录开始、结束、耗时及异常。"""
    started = perf_counter()
    LOGGER.info("开始 %s", name)
    try:
        result = function(*args)
    except Exception:
        LOGGER.exception("失败 %s，耗时 %.3f 秒", name, perf_counter() - started)
        raise
    LOGGER.info("完成 %s，耗时 %.3f 秒", name, perf_counter() - started)
    return result


def load_data(csv_path: Path) -> pd.DataFrame:
    """读取一次源文件，规范字段。行索引保留为内部来源行号。"""
    data = pd.read_csv(
        csv_path, usecols=list(SOURCE_FIELDS), dtype="string",
        keep_default_na=False, na_values=[""],
    ).rename(columns=SOURCE_FIELDS)
    for field in ("invoice_no", "stock_code", "description", "customer_id", "country"):
        data[field] = data[field].str.strip().replace("", pd.NA)

    quantity = pd.to_numeric(data["quantity"], errors="coerce")
    valid_quantity = (
        np.isfinite(quantity) & quantity.mod(1).eq(0)
        & quantity.gt(-(2**63)) & quantity.lt(2**63)
    ).fillna(False)
    price = pd.to_numeric(data["unit_price"], errors="coerce").astype("float64")
    invoice_dates = pd.to_datetime(data["invoice_datetime"], format="ISO8601", errors="coerce")
    data["quantity"] = quantity.where(valid_quantity).astype("Int64")
    data["unit_price"] = price.where(np.isfinite(price))
    data["invoice_datetime"] = invoice_dates
    total = data["quantity"].astype("float64") * data["unit_price"]
    data["total_amount"] = total.where(np.isfinite(total))
    data["is_cancel"] = data["invoice_no"].str.upper().str.startswith("C", na=False)
    LOGGER.info(
        "读取 %d 行，数量无效或缺失 %d，单价无效或缺失 %d，时间无效或缺失 %d",
        len(data), data["quantity"].isna().sum(), data["unit_price"].isna().sum(),
        data["invoice_datetime"].isna().sum(),
    )
    return data


def filter_real_sales(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, float]:
    """保留正向商品明细，并按首个排除原因对账。"""
    stock = data["stock_code"]
    code = stock.str.upper()
    description = data["description"].str.replace(r"\s+", " ", regex=True).str.casefold()
    verified = stock.map(VERIFIED_NAMES).astype("string")
    verified_description = description.eq(verified.str.casefold()).fillna(False)
    common_code = stock.str.fullmatch(r"[0-9]+[A-Za-z]*", na=False)
    required = ["invoice_no", "stock_code", "invoice_datetime", "quantity", "unit_price", "total_amount"]
    rules = [
        ("取消发票", data["is_cancel"]),
        ("坏账调整", code.eq("B") | description.eq("adjust bad debt")),
        ("其他已识别非商品编码", code.isin(NON_PRODUCT_CODES)),
        ("关键字段缺失或无效", data[required].isna().any(axis=1)),
        ("数量或单价非正", data["quantity"].le(0) | data["unit_price"].le(0)),
        ("已识别业务备注", description.str.fullmatch(BUSINESS_NOTES, na=False)),
        ("特殊格式商品身份待核实", ~common_code & ~verified_description),
    ]
    rejected_reason = pd.Series(pd.NA, index=data.index, dtype="string")
    for reason, mask in rules:
        rejected_reason.loc[rejected_reason.isna() & mask.fillna(False)] = reason

    included = rejected_reason.isna()
    sales = data.loc[included, FACT_COLUMNS].copy()
    use_standard = verified_description.loc[included] | sales["description"].isna()
    sales["description"] = sales["description"].mask(
        use_standard & verified.loc[included].notna(), verified.loc[included]
    )
    sales["quantity"] = sales["quantity"].astype("int64")
    excluded = rejected_reason.value_counts().reindex([reason for reason, _ in rules], fill_value=0)
    pending_amount = data.loc[rejected_reason.eq("特殊格式商品身份待核实").fillna(False), "total_amount"].sum()
    LOGGER.info("销售明细 %d 行，排除原因 %s，待核实商品正向金额 %.4f", len(sales), excluded.to_dict(), pending_amount)
    return sales, excluded, float(pending_amount)


def primary_country(known: pd.DataFrame) -> pd.Series:
    """按独立发票投票，排除一票多国，按最近时间和国家名打破并列。"""
    invoice_keys = ["customer_id", "invoice_no"]
    countries = (known.dropna(subset=["country"])
                 .groupby(invoice_keys + ["country"], as_index=False)
                 .agg(latest=("invoice_datetime", "max")))
    conflicting = countries.duplicated(invoice_keys, keep=False)
    LOGGER.info("国家冲突、不参与投票的发票数 %d",
                len(countries.loc[conflicting, invoice_keys].drop_duplicates()))
    votes = (countries.loc[~conflicting].groupby(["customer_id", "country"], as_index=False)
             .agg(votes=("invoice_no", "size"), latest=("latest", "max"))
             .sort_values(["customer_id", "votes", "latest", "country"], ascending=[True, False, False, True]))
    return votes.drop_duplicates("customer_id").set_index("customer_id")["country"]


def compute_rfm(sales: pd.DataFrame, reference_date: pd.Timestamp) -> pd.DataFrame:
    """按客户汇总正向销售，购买次数按不同发票号计算。"""
    if pd.isna(reference_date):
        raise ValueError("数据集没有有效发票日期，无法确定 RFM 基准日")
    known = sales.loc[sales["customer_id"].notna()]
    features = known.groupby("customer_id", sort=True).agg(
        frequency=("invoice_no", "nunique"), monetary=("total_amount", "sum"),
        first_purchase_date=("invoice_datetime", "min"), last_purchase_date=("invoice_datetime", "max"),
        unique_products=("stock_code", "nunique"),
    )
    for field in ("first_purchase_date", "last_purchase_date"):
        features[field] = features[field].dt.normalize()
    features["recency_days"] = (reference_date - features["last_purchase_date"]).dt.days
    features["country"] = primary_country(known).reindex(features.index).astype("string")
    features["is_one_time_buyer"] = features["frequency"].eq(1)
    LOGGER.info("RFM 基准日 %s，客户 %d 个，排除缺 ID 销售 %d 行",
                reference_date.date(), len(features), len(sales) - len(known))
    return features.reset_index()[CUSTOMER_COLUMNS]


def allocate_group(sales: pd.DataFrame, returns: pd.DataFrame):
    """按时间在单一客户与商品内查找候选，扣减源销售行的剩余数量。"""
    sale_times = sales["invoice_datetime"].to_numpy(dtype="datetime64[ns]")
    source_rows = sales.index.to_numpy()
    invoices = sales["invoice_no"].to_numpy()
    quantities = sales["quantity"].to_numpy(dtype="int64")
    remaining = quantities.copy()
    cutoffs = np.searchsorted(
        sale_times, returns["invoice_datetime"].to_numpy(dtype="datetime64[ns]"), side="left"
    )
    for row, needed, cutoff in zip(returns.index, -returns["quantity"].to_numpy(dtype="int64"), cutoffs):
        if not cutoff:
            yield row, None, None, "无更早的候选销售"
            continue
        available = remaining[:cutoff] >= needed
        exact = np.flatnonzero(available & (quantities[:cutoff] == needed))
        possible = exact if exact.size else np.flatnonzero(available)
        if not possible.size:
            enough_in_total = sum(map(int, remaining[:cutoff])) >= needed
            reason = "需跨发票或多行分配" if enough_in_total else "候选销售剩余量不足"
            yield row, None, None, reason
            continue
        latest = possible[-1]
        ties = possible[sale_times[possible] == sale_times[latest]]
        if (invoices[ties] != invoices[latest]).any():
            yield row, None, None, "最近时刻有多张候选发票"
            continue
        remaining[latest] -= needed
        yield row, source_rows[latest], invoices[latest], MATCHED[0] if exact.size else MATCHED[1]


def match_returns(data: pd.DataFrame, sales: pd.DataFrame):
    """保留全部取消行；仅为涉及的客户和商品建立候选组。"""
    returns = data.loc[data["is_cancel"], FACT_COLUMNS].copy()
    returns["matched_original_invoice"] = pd.Series(pd.NA, index=returns.index, dtype="string")
    status = pd.Series("无更早的候选销售", index=returns.index, dtype="string")
    source = pd.Series(pd.NA, index=returns.index, dtype="Int64")
    keys = ["customer_id", "stock_code"]
    missing = returns[keys + ["invoice_datetime"]].isna().any(axis=1)
    negative_quantity = returns["quantity"].lt(0).fillna(False)
    status.loc[missing] = "缺客户、商品或时间"
    status.loc[~missing & ~negative_quantity] = "数量无效或非负"

    eligible = returns.loc[~missing & negative_quantity].sort_values("invoice_datetime", kind="stable")
    return_keys = pd.MultiIndex.from_frame(eligible[keys]).unique()
    candidates = sales.loc[pd.MultiIndex.from_frame(sales[keys]).isin(return_keys)]
    candidates = candidates.sort_values("invoice_datetime", kind="stable")
    positions = candidates.groupby(keys, sort=False).indices
    for key, group in eligible.groupby(keys, sort=False):
        if key not in positions:
            continue
        for row, source_row, invoice, result in allocate_group(candidates.iloc[positions[key]], group):
            status.at[row] = result
            if source_row is not None:
                source.at[row] = source_row
                returns.at[row, "matched_original_invoice"] = invoice

    LOGGER.info("取消匹配状态 %s", status.value_counts().to_dict())
    unmatched = status.loc[~status.isin(MATCHED)]
    for reason, rows in unmatched.groupby(unmatched):
        LOGGER.info("未匹配原因 %s，发票示例 %s", reason,
                    returns.loc[rows.index, "invoice_no"].drop_duplicates().head(3).tolist())
    return returns[RETURN_COLUMNS], status, source


def validate_output(data, sales, excluded, features, returns, status, source, reference_date):
    """对账输出粒度、金额、匹配条件及累计退货量。"""
    assert list(sales.columns) == FACT_COLUMNS
    assert len(sales) + int(excluded.sum()) == len(data), "销售筛选行数未对平"
    assert sales[["invoice_no", "stock_code", "invoice_datetime", "quantity",
                  "unit_price", "total_amount"]].notna().all().all()
    assert not sales["invoice_no"].str.upper().str.startswith("C", na=False).any()
    assert not sales["stock_code"].str.upper().isin(NON_PRODUCT_CODES).any()
    assert sales["quantity"].gt(0).all() and sales["unit_price"].gt(0).all()
    assert np.isfinite(sales["total_amount"]).all() and sales["total_amount"].ge(0).all()
    assert np.allclose(sales["total_amount"], sales["quantity"] * sales["unit_price"])
    for frame in (sales, returns):
        for field in ("invoice_no", "stock_code", "customer_id"):
            assert isinstance(frame[field].dtype, pd.StringDtype)
        assert pd.api.types.is_datetime64_any_dtype(frame["invoice_datetime"].dtype)
        assert pd.api.types.is_integer_dtype(frame["quantity"].dtype)
        for field in ("unit_price", "total_amount"):
            assert pd.api.types.is_float_dtype(frame[field].dtype)

    known = sales.loc[sales["customer_id"].notna()]
    assert list(features.columns) == CUSTOMER_COLUMNS
    assert features["customer_id"].is_unique and features["customer_id"].notna().all()
    assert len(features) == known["customer_id"].nunique()
    assert features["frequency"].sum() == len(known[["customer_id", "invoice_no"]].drop_duplicates())
    assert features["frequency"].gt(0).all() and features["unique_products"].gt(0).all()
    assert features["recency_days"].ge(0).all()
    assert features["first_purchase_date"].le(features["last_purchase_date"]).all()
    assert features["last_purchase_date"].le(reference_date).all()
    assert features["is_one_time_buyer"].eq(features["frequency"].eq(1)).all()
    assert np.isclose(features["monetary"].sum(), known["total_amount"].sum(), rtol=0, atol=1e-6)

    assert list(returns.columns) == RETURN_COLUMNS
    assert returns.index.equals(data.index[data["is_cancel"]]), "取消明细未完整保留"
    assert isinstance(returns["matched_original_invoice"].dtype, pd.StringDtype)
    assert status.index.equals(returns.index) and status.notna().all()
    calculable = returns["total_amount"].notna()
    assert np.allclose(returns.loc[calculable, "total_amount"],
                       returns.loc[calculable, "quantity"].astype("float64")
                       * returns.loc[calculable, "unit_price"])
    matched = status.isin(MATCHED)
    assert np.array_equal(matched, source.notna())
    assert np.array_equal(matched, returns["matched_original_invoice"].notna())
    actual = returns.loc[matched]
    source_rows = source.loc[matched].astype("int64")
    original = sales.loc[source_rows.to_numpy()].set_axis(actual.index)
    for field in ("customer_id", "stock_code"):
        assert actual[field].eq(original[field]).all()
    assert actual["matched_original_invoice"].eq(original["invoice_no"]).all()
    assert original["invoice_datetime"].lt(actual["invoice_datetime"]).all()
    returned_quantity = -actual["quantity"]
    exact = status.loc[matched].eq(MATCHED[0])
    assert returned_quantity.gt(0).all()
    assert returned_quantity.loc[exact].eq(original.loc[exact, "quantity"]).all()
    assert returned_quantity.loc[~exact].lt(original.loc[~exact, "quantity"]).all()
    allocated = returned_quantity.groupby(source_rows).sum()
    assert allocated.le(sales.loc[allocated.index, "quantity"]).all(), "累计退货量超过原销售量"
    LOGGER.info("行数、金额、时间先后及退货累计数量校验通过")


def build_validation_report(data, sales, excluded, pending_amount, features, returns, status, reference_date):
    """报告三张表的行数、字段空值率和关键字段分布。"""
    lines = ["# Q3 管道校验报告", "", f"原始明细 {len(data):,} 行。RFM 基准日为 {reference_date.date()}。", ""]
    datasets = [
        ("sales_facts", sales, ["quantity", "unit_price", "total_amount"]),
        ("customer_features", features, ["recency_days", "frequency", "monetary", "unique_products"]),
        ("returns_log", returns, ["quantity", "total_amount"]),
    ]
    for name, frame, fields in datasets:
        lines += [f"## {name}", "", f"行数 **{len(frame):,}**", "",
                  "| 字段 | 空值行数 | 空值率 |", "|---|---:|---:|"]
        for field, count in frame.isna().sum().items():
            rate = f"{count / len(frame):.4%}" if len(frame) else "—"
            lines.append(f"| `{field}` | {count:,} | {rate} |")
        lines += ["", "| 关键字段 | 最小值 | 中位数 | P90 | 最大值 |", "|---|---:|---:|---:|---:|"]
        for field in fields:
            values = frame[field].dropna()
            stats = (values.min(), values.median(), values.quantile(0.9), values.max()) if len(values) else ()
            cells = [f"{value:,.4f}" for value in stats] if stats else ["—"] * 4
            lines.append(f"| `{field}` | " + " | ".join(cells) + " |")
        lines.append("")

    anonymous = sales.loc[sales["customer_id"].isna()]
    lines += ["## 销售与客户金额对账", "",
              f"- 正向商品金额合计 {sales['total_amount'].sum():,.4f}",
              f"- 缺客户 ID 的合格销售 {len(anonymous):,} 行，涉及 {anonymous['invoice_no'].nunique():,} 张发票，"
              f"金额 {anonymous['total_amount'].sum():,.4f}",
              f"- RFM 客户金额合计 {features['monetary'].sum():,.4f}",
              f"- 一次购买客户 {features['is_one_time_buyer'].sum():,} 位",
              f"- 待核实商品编码的正向金额 {pending_amount:,.4f}", "", "按首个排除原因对账：", ""]
    lines.extend(f"- {reason} {count:,} 行" for reason, count in excluded.items())

    states = [*MATCHED, "缺客户、商品或时间", "数量无效或非负", "无更早的候选销售",
              "候选销售剩余量不足", "需跨发票或多行分配", "最近时刻有多张候选发票"]
    lines += ["", "## 取消匹配", "", "| 状态 | 行数 |", "|---|---:|"]
    lines.extend(f"| {label} | {count:,} |" for label, count in status.value_counts().reindex(states, fill_value=0).items())
    rate = f"{status.isin(MATCHED).mean():.4%}" if len(returns) else "—"
    lines += ["", f"匹配率 **{rate}**。", "",
              "在同客户、同商品的销售候选池内，按取消时间处理，同一时刻按输入行序。"
              "优先选择最近的等量候选，其次尝试最近且剩余可退量足够的单条销售。"
              "每次匹配扣减原明细的剩余量。候选有歧义或需要拆到多条明细时，原单留空。"
              "部分退货是推断，未匹配表示在当前候选池和规则下没有可报告的原单。", ""]
    return "\n".join(lines)


def write_outputs(output_dir, sales, features, returns, report):
    """先写完整临时产物，写成功后再替换正式文件。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir.parent / "validation_report.md"
    tables = {"sales_facts.parquet": sales, "customer_features.parquet": features,
              "returns_log.parquet": returns}
    with TemporaryDirectory(prefix=".q3-", dir=output_dir.parent) as directory:
        temp = Path(directory)
        for name, frame in tables.items():
            run_step(f"写入 {name}", lambda: frame.to_parquet(temp / name, engine="pyarrow", index=False))
        (temp / report_path.name).write_text(report, encoding="utf-8")
        for name in tables:
            (temp / name).replace(output_dir / name)
        (temp / report_path.name).replace(report_path)
    LOGGER.info("校验报告已写入 %s", report_path)


def run_pipeline(csv_path: Path, output_dir: Path) -> None:
    """读取一次数据，生成、校验并发布全部输出。"""
    started = perf_counter()
    random.seed(SEED)
    np.random.seed(SEED)
    data = run_step("读取及标准化", load_data, csv_path)
    reference_date = data["invoice_datetime"].max()
    if pd.notna(reference_date):
        reference_date = reference_date.normalize()
    sales, excluded, pending_amount = run_step("筛选真实销售", filter_real_sales, data)
    features = run_step("计算 RFM", compute_rfm, sales, reference_date)
    returns, status, source = run_step("匹配取消明细", match_returns, data, sales)
    run_step("校验三份输出", validate_output, data, sales, excluded, features, returns, status, source, reference_date)
    report = run_step("生成校验报告", build_validation_report, data, sales, excluded, pending_amount, features,
                      returns, status, reference_date)
    run_step("发布提交产物", write_outputs, output_dir, sales, features, returns, report)
    LOGGER.info("Q3 总耗时 %.3f 秒", perf_counter() - started)


def main():
    parser = argparse.ArgumentParser(description="生成 Q3 销售、客户及取消数据")
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "data" / "online_retail_ii.csv")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "outputs")
    args = parser.parse_args()
    log = args.output_dir.parent / "pipeline_log.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(log, mode="w", encoding="utf-8")])
    run_pipeline(args.input, args.output_dir)


if __name__ == "__main__":
    main()
