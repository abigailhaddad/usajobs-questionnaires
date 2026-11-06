#!/usr/bin/env python3
"""Build the release tables from a folder of raw questionnaire text files.

    python3 scripts/build_release.py RAW_DIR LINKS_CSV [--out build/release] [--limit N]

RAW_DIR holds files named usastaffing_<id>.txt and monster_<id>.txt (the page text, saved as is).
LINKS_CSV (optional) maps each questionnaire URL to the announcement that linked it.
Writes questionnaires.parquet, questions.parquet and sections.parquet, and a stats.json.
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from usajq.ids import portal_and_id  # noqa: E402
from usajq.parse_usastaffing import parse, text_hash  # noqa: E402

OPTION_T = pa.list_(pa.struct([("letter", pa.string()), ("text", pa.string())]))
Q_SCHEMA = pa.schema([
    ("questionnaire_id", pa.string()), ("portal", pa.string()), ("question_id", pa.string()),
    ("question_ordinal", pa.int32()), ("block_index", pa.int32()), ("section", pa.string()), ("section_kind", pa.string()),
    ("question_number", pa.int32()), ("question_text", pa.string()), ("question_type", pa.string()),
    ("n_options", pa.int32()), ("options", OPTION_T), ("options_lettered", pa.bool_()),
    ("trailing_text", pa.string()), ("announcement_number", pa.string()), ("agency", pa.string()),
])
S_SCHEMA = pa.schema([
    ("questionnaire_id", pa.string()), ("portal", pa.string()), ("block_index", pa.int32()),
    ("section", pa.string()), ("section_kind", pa.string()), ("intro_text", pa.string()),
])
QN_SCHEMA = pa.schema([
    ("questionnaire_id", pa.string()), ("portal", pa.string()), ("source_url", pa.string()),
    ("method", pa.string()), ("retrieved_at", pa.string()), ("link_found_at", pa.string()),
    ("parse_status", pa.string()), ("n_questions", pa.int32()), ("n_sections", pa.int32()),
    ("n_chars", pa.int32()), ("text_sha256", pa.string()), ("preview_banner", pa.bool_()),
    ("position_title", pa.string()), ("agency", pa.string()), ("announcement_number", pa.string()),
    ("open_period", pa.string()), ("open_date", pa.string()), ("close_date", pa.string()),
    ("n_announcements", pa.int32()), ("usajobs_control_numbers", pa.list_(pa.string())),
    ("hiring_agency", pa.string()), ("occupation_series", pa.string()), ("raw_text", pa.string()),
])


def load_links(path):
    """questionnaire (portal, id) -> info from the announcements that linked it."""
    if not path or not Path(path).exists():
        return {}
    df = pd.read_csv(path, dtype=str).fillna("")
    out = {}
    for url, g in df.groupby("questionnaire_url", sort=False):
        portal, qid = portal_and_id(url)
        if not qid:
            continue
        g = g.sort_values("position_open_date")
        key = (portal, qid)
        prev = out.get(key)
        rec = {
            "source_url": url,
            "controls": sorted(set(g["usajobs_control_number"])),
            "hiring_agency": g.iloc[0]["hiring_agency"] or None,
            "series": g.iloc[0]["occupation_series"] or None,
            "found": g["extracted_date"].min() or None,
        }
        if prev:
            rec["controls"] = sorted(set(prev["controls"]) | set(rec["controls"]))
        out[key] = rec
    return out


class Writers:
    def __init__(self, out):
        out.mkdir(parents=True, exist_ok=True)
        kw = dict(compression="zstd", compression_level=6)
        self.q = pq.ParquetWriter(out / "questions.parquet", Q_SCHEMA, **kw)
        self.s = pq.ParquetWriter(out / "sections.parquet", S_SCHEMA, **kw)
        self.n = pq.ParquetWriter(out / "questionnaires.parquet", QN_SCHEMA, **kw)

    def close(self):
        for w in (self.q, self.s, self.n):
            w.close()


def flush(w, qrows, srows, nrows):
    if qrows:
        w.q.write_table(pa.Table.from_pylist(qrows, schema=Q_SCHEMA))
    if srows:
        w.s.write_table(pa.Table.from_pylist(srows, schema=S_SCHEMA))
    if nrows:
        w.n.write_table(pa.Table.from_pylist(nrows, schema=QN_SCHEMA))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw_dir")
    ap.add_argument("links_csv", nargs="?")
    ap.add_argument("--out", default="build/release")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--method", default="live")
    ap.add_argument("--state", help="state/attempts.jsonl: fills retrieved_at and source_url for fetched pages")
    args = ap.parse_args()
    raw = Path(args.raw_dir)
    links = load_links(args.links_csv)
    fetched = {}
    if args.state and Path(args.state).exists():
        for line in Path(args.state).read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec["outcome"] == "ok":
                    fetched[(rec["portal"], rec["id"])] = rec
    files = sorted(p for p in raw.iterdir() if re.match(r"^(usastaffing|monster)_\d+\.txt$", p.name))
    if args.limit:
        files = files[: args.limit]
    w = Writers(Path(args.out))
    stats = collections.Counter()
    qrows, srows, nrows = [], [], []
    for i, p in enumerate(files):
        portal, qid = p.stem.split("_", 1)
        text = p.read_text(encoding="utf-8", errors="replace")
        info = links.get((portal, qid), {})
        base = {
            "questionnaire_id": qid, "portal": portal,
            "source_url": info.get("source_url") or fetched.get((portal, qid), {}).get("url"),
            "method": args.method, "retrieved_at": fetched.get((portal, qid), {}).get("ts"),
            "link_found_at": info.get("found"),
            "n_chars": len(text), "text_sha256": text_hash(text),
            "n_announcements": len(info.get("controls", [])) or None,
            "usajobs_control_numbers": info.get("controls") or None,
            "hiring_agency": info.get("hiring_agency"), "occupation_series": info.get("series"),
        }
        if portal == "usastaffing":
            r = parse(text)
            keep_raw = r["parse_status"] in ("ok", "ok_missing_header", "no_questions")
            nrows.append({**base, "parse_status": r["parse_status"], "n_questions": len(r["questions"]),
                          "n_sections": len(r["sections"]), "preview_banner": r["preview_banner"],
                          "position_title": r["position_title"], "agency": r["agency"],
                          "announcement_number": r["announcement_number"], "open_period": r["open_period"],
                          "open_date": r["open_date"], "close_date": r["close_date"],
                          "raw_text": text if keep_raw else None})
            stats["usastaffing:" + r["parse_status"]] += 1
            for s in r["sections"]:
                srows.append({"questionnaire_id": qid, "portal": portal, "block_index": s["block_index"],
                              "section": s["section"], "section_kind": s["section_kind"],
                              "intro_text": s["intro_text"]})
            for ordinal, q in enumerate(r["questions"], 1):
                qrows.append({
                    "questionnaire_id": qid, "portal": portal,
                    "question_id": f"{qid}-{ordinal:03d}", "question_ordinal": ordinal,
                    "block_index": q["block_index"], "section": q["section"], "section_kind": q["section_kind"],
                    "question_number": q["question_number"], "question_text": q["question_text"],
                    "question_type": q["question_type"], "n_options": q["n_options"],
                    "options": [{"letter": o["letter"], "text": o["text"]} for o in q["options"]],
                    "options_lettered": q["options_lettered"], "trailing_text": q["trailing_text"],
                    "announcement_number": r["announcement_number"], "agency": r["agency"],
                })
        else:  # Monster pages are flattened to one line of text: kept as is, not split into questions
            nrows.append({**base, "parse_status": "monster_not_parsed", "n_questions": 0, "n_sections": 0,
                          "preview_banner": False, "position_title": None, "agency": None,
                          "announcement_number": None, "open_period": None, "open_date": None,
                          "close_date": None, "raw_text": text})
            stats["monster:monster_not_parsed"] += 1
        if (i + 1) % 2000 == 0:
            flush(w, qrows, srows, nrows)
            qrows, srows, nrows = [], [], []
            print(f"{i+1}/{len(files)}", flush=True)
    flush(w, qrows, srows, nrows)
    w.close()
    stats["files"] = len(files)
    out = Path(args.out)
    (out / "stats.json").write_text(json.dumps(dict(stats), indent=1))
    print(dict(stats))


if __name__ == "__main__":
    main()
