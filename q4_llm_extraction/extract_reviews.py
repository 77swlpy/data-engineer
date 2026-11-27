# -*- coding: utf-8 -*-
"""extract_reviews.py - production batched pipeline (Q4.1 A-variant).

Config: model deepseek-flash, batch=20, thinking disabled, compact prompt, max_tokens=2500.
Features: checkpoint/resume, per-batch persistence, validation (schema + verbatim evidence +
duplicate category), retry, source_row_id backfill, token/cost accounting, failed log.

  python extract_reviews.py --dry-run
  python extract_reviews.py --limit 40 --batch 20
  python extract_reviews.py                      # full 14,445 (not executed in this project)
"""
import argparse, json, os, sys, threading, time, urllib.request

import pandas as pd

Q = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.dirname(Q)
MODEL = "deepseek-flash"
BATCH_DEFAULT = 20
MAX_TOKENS = 2500
CATS = {"delivery_late", "wrong_product", "quality_defect", "missing_item",
        "seller_communication", "packaging", "other"}
SEV = {"low", "medium", "high"}
LOCK = threading.Lock()

PROMPT_HEAD = open(os.path.join(Q, "prompt_template.txt"), encoding="utf-8").read()

def load_rows():
    df = pd.read_csv(os.path.join(DATA, "olist_order_reviews_dataset.csv"), dtype=str,
                     keep_default_na=False, na_values=[""])
    df["source_row_id"] = ["R%06d" % (i + 2) for i in range(len(df))]
    df["score"] = pd.to_numeric(df["review_score"])
    df["text"] = df["review_comment_message"].fillna("")
    df = df[(df["score"] <= 3) & (df["text"].str.strip().ne(""))]
    return df[["source_row_id", "review_id", "order_id", "score", "text"]].reset_index(drop=True)

def build_prompt(chunk):
    blocks = ["[%s] %s" % (r["review_id"], str(r["text"]).replace("\n", " ")) for _, r in chunk.iterrows()]
    return PROMPT_HEAD + "\n".join(blocks)

def call(key, prompt, max_tokens=MAX_TOKENS):
    body = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request("https://api.deepseek.com/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    t0 = time.time()
    d = json.loads(urllib.request.urlopen(req, timeout=300).read())
    return d, round(time.time() - t0, 2)

def validate(obj, rid, text):
    errs = []
    if str(obj.get("review_id")) != str(rid): errs.append("review_id")
    if not isinstance(obj.get("issues"), list): return errs + ["issues_not_list"]
    seen = set()
    for i in obj["issues"]:
        if i.get("category") not in CATS: errs.append("bad_category")
        if i.get("severity") not in SEV: errs.append("bad_severity")
        if i.get("category") in seen: errs.append("duplicate_category")
        seen.add(i.get("category"))
        q = i.get("evidence_quote", "")
        if not isinstance(q, str) or not q or q not in text: errs.append("quote_not_in_source")
        if not str(i.get("evidence_quote_en", "")).strip(): errs.append("missing_en")
    if not (-1 <= float(obj.get("sentiment_score", 0)) <= 1): errs.append("sentiment_range")
    if not (0 <= float(obj.get("confidence", 0)) <= 1): errs.append("confidence_range")
    if not isinstance(obj.get("actionable_for_seller"), bool): errs.append("actionable_not_bool")
    return errs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=BATCH_DEFAULT)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows = load_rows()
    if a.limit: rows = rows.head(a.limit)
    ck_path = os.path.join(Q, "processing_checkpoint.json")
    ck = json.load(open(ck_path, encoding="utf-8")) if os.path.exists(ck_path) else {}
    done = set(ck.get("done_ids", []))
    todo = rows[~rows["source_row_id"].isin(done)].reset_index(drop=True)

    if a.dry_run:
        p = build_prompt(todo.head(min(a.batch, len(todo))))
        print(json.dumps({"eligible": len(rows), "todo": len(todo), "batch": a.batch,
                          "prompt_chars": len(p), "est_calls": -(-len(todo)//a.batch)}, ensure_ascii=False))
        return

    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print(json.dumps({"error": "DEEPSEEK_API_KEY not set", "todo": len(todo)})); sys.exit(2)

    results_path = os.path.join(Q, "results.jsonl")
    failed_path = os.path.join(Q, "failed_batch.json")
    tin = tout = 0
    failed = []
    t_all = time.time()

    chunks = [todo.iloc[i:i+a.batch] for i in range(0, len(todo), a.batch)]

    def work(chunk):
        prompt = build_prompt(chunk)
        last = None
        for mt in (MAX_TOKENS, 4000):
            try:
                d, lat = call(key, prompt, mt)
                items = json.loads(d["choices"][0]["message"]["content"]).get("results", [])
                return {"items": items, "usage": d.get("usage", {}), "lat": lat,
                        "n": len(chunk), "err": None}
            except Exception as e:
                last = repr(e)[:200]
        return {"items": [], "usage": {}, "lat": 0, "n": len(chunk), "err": last}

    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = [ex.submit(work, ch) for ch in chunks]
        for f in as_completed(futs):
            r = f.result()
            by_id = {}
            for o in r["items"]:
                rid = str(o.get("review_id"))
                row = todo[todo["review_id"].astype(str) == rid]
                if len(row) == 0:
                    continue
                text = row.iloc[0]["text"]
                errs = validate(o, rid, text)
                if errs:
                    failed.append({"review_id": rid, "source_row_id": row.iloc[0]["source_row_id"], "errors": errs})
                else:
                    by_id[rid] = o
            with LOCK:
                with open(results_path, "a", encoding="utf-8") as fh:
                    for rid, o in by_id.items():
                        row = todo[todo["review_id"].astype(str) == rid].iloc[0]
                        fh.write(json.dumps({"source_row_id": row["source_row_id"], "review_id": rid,
                                             "order_id": row["order_id"], "review_score": int(row["score"]),
                                             "extraction": o}, ensure_ascii=False) + "\n")
                tin += r["usage"].get("prompt_tokens", 0) or 0
                tout += r["usage"].get("completion_tokens", 0) or 0
                ck.setdefault("done_ids", []).extend([todo[todo["review_id"].astype(str) == rid].iloc[0]["source_row_id"] for rid in by_id])
                ck.update({"model": MODEL, "batch": a.batch, "done": len(ck["done_ids"]),
                           "total_eligible": len(rows), "tokens_in": ck.get("tokens_in", 0),
                           "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
                json.dump(ck, open(ck_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                if failed:
                    json.dump(failed, open(failed_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(json.dumps({"processed": len(todo), "ok": len(ck["done_ids"]), "failed": len(failed),
                      "tokens_in": tin, "tokens_out": tout, "wall_s": round(time.time()-t_all, 1)}, ensure_ascii=False))

if __name__ == "__main__":
    from concurrent.futures import ThreadPoolExecutor, as_completed
    main()
