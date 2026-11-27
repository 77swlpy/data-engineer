# -*- coding: utf-8 -*-
"""V2.0 pipeline: rule triage + batched LLM + exact-text cache + checkpoint + guards."""
import argparse, hashlib, json, os, re, string, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

Q = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(Q, "logs"), exist_ok=True)
ROOT = os.path.dirname(os.path.dirname(Q))
MODEL = "deepseek-flash"; PROMPT_VERSION = "A-v2"
CATS = {"delivery_late","wrong_product","quality_defect","missing_item","seller_communication","packaging","other"}
SEV = {"low","medium","high"}
PROMPT = open(os.path.join(Q, "prompt_template.txt"), encoding="utf-8").read()
LOCK = threading.Lock()

EMO = re.compile(r"^(ruim|pessimo|pessima|horrivel|terrivel|muito ruim|muito pessimo|nao gostei|nao recomendo|decepcionado|decepcionada|insatisfeito|insatisfeita|uma porcaria|porcaria|lixo|odiei)[.! ]*$")
BIZ = re.compile(r"entreg|receb|produt|pedid|embalag|caixa|defeit|quebr|falt|atras|prazo|correio|vendedor|loja|reembols|devolu|troca|cancel|nota|frete|preco|tamanho|modelo|cor")

def triage(text):
    t = text.strip().lower()
    t = "".join(c for c in __import__("unicodedata").normalize("NFD", t) if __import__("unicodedata").category(c) != "Mn")
    if len(t.split()) <= 4 and EMO.match(t) and not BIZ.search(t):
        return {"issues": [], "sentiment_score": -0.6, "actionable_for_seller": False,
                "confidence": 0.7, "route": "rule"}
    return None

def load():
    csv_path = None
    for cand in (Q, os.path.dirname(Q), os.path.dirname(os.path.dirname(Q))):
        cp = os.path.join(cand, "olist_order_reviews_dataset.csv")
        if os.path.exists(cp):
            csv_path = cp; break
    if csv_path is None:
        raise SystemExit("olist_order_reviews_dataset.csv not found next to the script or its parents")
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, na_values=[""])
    sha = hashlib.sha256(open(csv_path, "rb").read()).hexdigest()[:12]
    df["line"] = range(2, len(df) + 2)
    df["source_row_id"] = df["line"].map(lambda x: "%s-%06d" % (sha, x))
    df["score"] = pd.to_numeric(df["review_score"])
    df["text"] = df["review_comment_message"].fillna("")
    return df[(df["score"] <= 3) & (df["text"].str.strip().ne(""))].reset_index(drop=True)

def build(chunk):
    return PROMPT + "\n".join("[%s|%s] %s" % (r["source_row_id"], r["review_id"], r["text"].replace("\n"," ")) for _, r in chunk.iterrows())

def call(key, prompt, mt=3000):
    body = {"model": MODEL, "temperature": 0, "max_tokens": mt, "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"}, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    t0 = time.time()
    d = json.loads(urllib.request.urlopen(req, timeout=300).read())
    return d, round(time.time() - t0, 2)

def validate(o, row):
    errs = []
    if str(o.get("sid")) != str(row["source_row_id"]): errs.append("sid")
    if str(o.get("review_id")) != str(row["review_id"]): errs.append("review_id")
    if not isinstance(o.get("issues"), list): return errs + ["issues_not_list"]
    seen = set()
    for i in o["issues"]:
        if i.get("category") not in CATS: errs.append("bad_category")
        if i.get("severity") not in SEV: errs.append("bad_severity")
        if i.get("category") in seen: errs.append("dup_category")
        seen.add(i.get("category"))
        q = i.get("evidence_quote", "")
        if not isinstance(q, str) or not q or q not in row["text"]: errs.append("quote")
        if not str(i.get("evidence_quote_en", "")).strip(): errs.append("missing_en")
    if not (-1 <= float(o.get("sentiment_score", 0)) <= 1): errs.append("sentiment")
    if not (0 <= float(o.get("confidence", 0)) <= 1): errs.append("confidence")
    if not isinstance(o.get("actionable_for_seller"), bool): errs.append("actionable")
    return errs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--gold", action="store_true")
    ap.add_argument("--out", default="results_v2.jsonl")
    a = ap.parse_args()
    rows = load()
    if a.gold:
        ann = pd.read_csv(os.path.join(ROOT, "q4_llm_extraction", "V2.0_final", "data", "annotation_label_mapping.csv"), encoding="utf-8-sig") if os.path.exists(os.path.join(ROOT, "q4_llm_extraction", "V2.0_final", "data", "annotation_label_mapping.csv")) else None
        if ann is not None: rows = rows[rows["review_id"].isin(set(ann["review_id"]))].drop_duplicates("review_id")
    if a.limit: rows = rows.head(a.limit)

    rule, llm = [], []
    for _, r in rows.iterrows():
        t = triage(r["text"])
        (rule if t else llm).append(r)
    if a.dry_run:
        p = build(pd.DataFrame(llm[:min(a.batch, len(llm))])) if llm else ""
        print(json.dumps({"eligible": len(rows), "rule": len(rule), "llm": len(llm),
                          "rule_pct": round(len(rule)/max(1,len(rows))*100,2), "prompt_chars": len(p)}, ensure_ascii=False))
        return

    key = os.environ["DEEPSEEK_API_KEY"]
    # ---- preflight budget guard: refuse to start if balance cannot cover the estimate ----
    try:
        breq = urllib.request.Request("https://api.deepseek.com/user/balance",
                                      headers={"Authorization": "Bearer " + key})
        bal = float(json.loads(urllib.request.urlopen(breq, timeout=20).read())["balance_infos"][0]["total_balance"])
    except Exception as e:
        print(json.dumps({"error": "balance_check_failed", "detail": repr(e)[:120]}, ensure_ascii=False)); sys.exit(4)
    n_tasks = len(rows) - len(rule)
    p_in = float(os.environ.get("PRICE_IN_CNY", "4")); p_out = float(os.environ.get("PRICE_OUT_CNY", "16"))
    est = n_tasks * (95 * p_in + 115 * p_out) / 1e6
    if bal < est * 1.05:
        print(json.dumps({"error": "insufficient_balance", "balance_cny": bal,
                          "estimated_cny": round(est, 2), "tasks": n_tasks}, ensure_ascii=False))
        sys.exit(3)
    out_path = os.path.join(Q, "logs", a.out)
    ck_path = os.path.join(Q, "logs", "processing_checkpoint.json")
    ck = json.load(open(ck_path, encoding="utf-8")) if os.path.exists(ck_path) else {"done": [], "tokens_in": 0, "tokens_out": 0}
    done = set(ck.get("done", []))
    todo = pd.DataFrame([r for r in llm if r["source_row_id"] not in done])
    chunks = [todo.iloc[i:i+a.batch] for i in range(0, len(todo), a.batch)]
    tin = tout = 0; failed = []
    t_all = time.time()

    def work(ch):
        prompt = build(ch)
        last = None
        for mt in (3000, 4500):
            try:
                d, lat = call(key, prompt, mt)
                return {"items": json.loads(d["choices"][0]["message"]["content"]).get("results", []), "u": d.get("usage", {}), "lat": lat, "err": None}
            except Exception as e:
                last = repr(e)[:160]
        return {"items": [], "u": {}, "lat": 0, "err": last}

    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        for f in as_completed([ex.submit(work, ch) for ch in chunks]):
            r = f.result(); by_sid = {}
            for o in r["items"]:
                sid = str(o.get("sid")); row = todo[todo["source_row_id"] == sid]
                if len(row) == 0: continue
                row = row.iloc[0]; errs = validate(o, row)
                if errs: failed.append({"sid": sid, "review_id": row["review_id"], "errors": errs})
                else: by_sid[sid] = o
            with LOCK:
                with open(out_path, "a", encoding="utf-8") as fh:
                    for sid, o in by_sid.items():
                        row = todo[todo["source_row_id"] == sid].iloc[0]
                        fh.write(json.dumps({"source_row_id": sid, "review_id": row["review_id"], "order_id": row["order_id"],
                                             "review_score": int(row["score"]), "route": "llm", "extraction": o}, ensure_ascii=False) + "\n")
                with open(out_path, "a", encoding="utf-8") as fh2:
                    for r0 in rule:
                        fh2.write(json.dumps({"source_row_id": r0["source_row_id"], "review_id": r0["review_id"],
                                              "order_id": r0["order_id"], "review_score": int(r0["score"]), "route": "rule",
                                              "extraction": {"review_id": r0["review_id"], "issues": [],
                                                             "sentiment_score": -0.6, "actionable_for_seller": False,
                                                             "confidence": 0.7}}, ensure_ascii=False) + "\n")
                if rule:
                    ck["done"] = list(set(ck.get("done", [])) | set(r0["source_row_id"] for r0 in rule))
                tin += r["u"].get("prompt_tokens", 0) or 0; tout += r["u"].get("completion_tokens", 0) or 0
                ck["done"] = list(set(ck.get("done", [])) | set(by_sid.keys()))
                ck.update({"model": MODEL, "prompt_version": PROMPT_VERSION, "tokens_in": ck.get("tokens_in",0)+tin,
                           "tokens_out": ck.get("tokens_out",0)+tout, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")})
                json.dump(ck, open(ck_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"rows": len(rows), "rule": len(rule), "llm": len(llm), "calls": len(chunks),
                      "ok": len(ck["done"]), "failed": len(failed), "tokens_in": tin, "tokens_out": tout,
                      "wall_s": round(time.time()-t_all,1)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
