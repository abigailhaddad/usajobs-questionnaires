#!/usr/bin/env python3
"""Write the Hugging Face dataset card (README.md) from the built tables, so every number is computed.

    python3 scripts/make_card.py [--release build/release] [--verify evidence/parse_verify.json]
"""
import argparse
import json
import re
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from usajq import config  # noqa: E402

EMAIL = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
PHONE = r"\(?\b[2-9][0-9]{2}\)?[ .-][0-9]{3}[ .-][0-9]{4}\b"
SSN = r"\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b"
GENERIC = re.compile(r"^(hr|staffing|jobs|careers|recruit|help|support|info|usajobs|jobhelp|mgshelp)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default="build/release")
    ap.add_argument("--verify", default="evidence/parse_verify.json")
    ap.add_argument("--as-of", default=None)
    args = ap.parse_args()
    R = Path(args.release)
    c = duckdb.connect()
    one = lambda s: c.execute(s).fetchone()
    allr = lambda s: c.execute(s).fetchall()
    Q, K, S = (f"'{R / n}.parquet'" for n in ("questionnaires", "questions", "sections"))

    n_all, = one(f"select count(*) from {Q}")
    by = {(p, s): n for p, s, n in allr(f"select portal, parse_status, count(*) from {Q} group by 1,2")}
    usa = sum(n for (p, _), n in by.items() if p == "usastaffing")
    mon = sum(n for (p, _), n in by.items() if p == "monster")
    ok = by.get(("usastaffing", "ok"), 0) + by.get(("usastaffing", "ok_missing_header"), 0)
    nq, = one(f"select count(*) from {K}")
    med, mx = one(f"select median(n_questions), max(n_questions) from {Q} where parse_status='ok'")
    types = allr(f"select question_type, count(*) from {K} group by 1 order by 2 desc")
    kinds = allr(f"select section_kind, count(*) from {K} group by 1 order by 2 desc")
    years = allr(f"select left(open_date,4), count(*) from {Q} where portal='usastaffing' and open_date is not null group by 1 order by 1")
    linked, = one(f"select count(*) from {Q} where source_url is not null")
    # ORDER BY, not min()/max(): on a Parquet file those can come back from truncated column statistics
    lf_min = one(f"select link_found_at from {Q} where link_found_at is not null order by 1 limit 1")[0][:10]
    lf_max = one(f"select link_found_at from {Q} where link_found_at is not null order by 1 desc limit 1")[0][:10]
    e_files, p_files, s_files, tot_text = one(
        f"select count(*) filter (where regexp_matches(raw_text,'{EMAIL}')), count(*) filter (where regexp_matches(raw_text,'{PHONE}')), "
        f"count(*) filter (where regexp_matches(raw_text,'{SSN}')), count(*) from {Q} where raw_text is not null")
    n_removed_pages, n_removed = one(
        f"select count(*) filter (where raw_text like '%[email removed]%'), "
        f"coalesce(sum(len(regexp_extract_all(raw_text, '\\[email removed\\]'))), 0) from {Q} where raw_text is not null")
    emails = {}
    for (e,) in allr(f"select unnest(regexp_extract_all(raw_text,'{EMAIL}')) from {Q} where raw_text is not null"):
        emails[e.lower()] = emails.get(e.lower(), 0) + 1
    name_like = [e for e in emails if re.match(r"^[a-z]+\.[a-z]+(\.[a-z]+)?@", e) and not GENERIC.match(e)]
    phones = {p for (p,) in allr(f"select unnest(regexp_extract_all(raw_text,'{PHONE}')) from {Q} where raw_text is not null")}
    v = json.loads(Path(args.verify).read_text()) if Path(args.verify).exists() else {}
    as_of = args.as_of or "2025 collection"
    n_ok_files = (v.get("status") or {}).get("ok", 0)
    n_mis = v.get("count_mismatch_files", 0)
    pct_mis = 100 * n_mis / max(n_ok_files, 1)
    n_lost = v.get("files_with_lost_lines", "?")
    n_checked = v.get("files", 0)

    yr = ", ".join(f"{y}: {n:,}" for y, n in years)
    ty = ", ".join(f"`{t}` {n:,}" for t, n in types)
    kd = ", ".join(f"`{k}` {n:,}" for k, n in kinds)
    card = f"""---
license: other
license_name: us-government-job-questionnaires-check-source-terms
language:
- en
tags:
- government
- jobs
- usajobs
- hiring
- federal
pretty_name: USAJOBS questionnaires (2025 collection)
configs:
- config_name: questions
  default: true
  data_files: data/questions/*.parquet
- config_name: questionnaires
  data_files: data/questionnaires/*.parquet
- config_name: sections
  data_files: data/sections/*.parquet
---

# USAJOBS questionnaires

The application questionnaires attached to federal job announcements on USAJOBS: the eligibility
questions, preference questions, conditions of employment and the assessment questions an applicant
answers before a resume is rated. {n_all:,} questionnaires, {nq:,} questions.

Unofficial copy of public pages. Questionnaires are templates: this dataset has the questions and
choices, never an applicant's answers.

## As of

This release is the {as_of}: pages read from the USA Staffing and Monster preview pages in 2025. The
exact time of each read was not recorded for this set, so `retrieved_at` is empty. `link_found_at` is
when the announcement's link was found, between {lf_min} and {lf_max}.
Earlier years are being added in batches; this card is regenerated with each release.

## Coverage

| Portal | Questionnaires | Parsed into questions |
|---|---|---|
| USA Staffing | {usa:,} | {ok:,} |
| Monster | {mon:,} | none: raw text only |

USA Staffing outcomes: {", ".join(f"{s} {n:,}" for (p, s), n in sorted(by.items()) if p == "usastaffing")}.
`html_shell` and `login_page` are saved pages that did not contain the questionnaire (the
text is not included). Open dates in the page header, by year: {yr}. Most are 2025 because these were
collected from 2025 announcements, but a questionnaire can be reused by a later announcement.
{linked:,} questionnaires are matched to the announcement that linked them
(`usajobs_control_numbers`, `hiring_agency`, `occupation_series`).

Agency-run portals (FAA, Marine Corps and others) and Workday, Taleo and similar systems are not
covered. Neither are announcements that never linked a questionnaire.

## Tables

Each table is a folder of Parquet files, one per release or batch (`part-<tag>.parquet`).

`data/questions/`, {nq:,} rows across the files there. One row per question.

| Column | Meaning |
|---|---|
| `question_id` | `<questionnaire_id>-<ordinal>`, unique |
| `questionnaire_id`, `portal` | Which questionnaire (text, as the portal numbers it) |
| `question_ordinal` | Position in the questionnaire, from 1 |
| `block_index`, `section`, `section_kind` | The heading it sits under (`Eligibilities`, `Preferences`, `Conditions of Employment`, `Assessment 1` ...) and a plain kind: `eligibility`, `preference`, `conditions`, `assessment` (`unknown` if text came before any heading) |
| `question_number` | The number the page shows. It can restart inside a heading and can begin above 1 |
| `question_text` | The question, with its own line breaks. May include instructions |
| `question_type` | `single_choice`, `multi_choice` (the text says to select all that apply), `dropdown`, or `free_text` (no choices on the page) |
| `n_options`, `options` | The answer choices, in page order: `letter` and `text` |
| `options_lettered` | False where the page shows choices without letters (a Yes / No pair). Letters are then assigned in page order |
| `trailing_text` | Text after the choices and before the next question: a follow-up field, a note, or the entries of a dropdown |
| `announcement_number`, `agency` | From the page header |

`data/questionnaires/`, {n_all:,} rows. One row per questionnaire: `parse_status`, `n_questions`,
`position_title`, `agency`, `announcement_number`, `open_period`, `open_date`, `close_date`, the
matched announcement fields, a hash of the text, and `raw_text`, the page text as read.

`data/sections/`. One row per heading, with `intro_text`: the instructions under the heading,
before its first question.

Question types: {ty}. Section kinds: {kd}. A parsed questionnaire has a median of {med:g} questions
and at most {mx:,}.

## Things to know

**What a question is.** The page text keeps no markup. A question starts at a line with its number,
and its choices are the lettered lines that follow. A numbered list inside a question's own text can
look like another question; where the numbers do not run in order the parser keeps it as text.
{n_mis} of {n_ok_files:,} parsed questionnaires have a numbered line whose
role is ambiguous (about {pct_mis:.2f}%).
They are listed in the repository.

**Notes between questions.** A paragraph that sits between two questions lands in the previous
question's `trailing_text`. `raw_text` in `questionnaires` has the page in its original order.

**Scoring is not shown.** The preview pages do not show how choices are scored or whether a question is
required, so those are not columns.

**The preview banner.** Every page reads "For preview purposes only". These are previews of the
questionnaire, as the portal shows them, not copies of anyone's application.

**Monster.** Monster pages are saved as one line of text and are not split into questions.

**Repeated text.** Many questionnaires share most of their questions (the veterans' preference question
alone is on thousands). Do not count questions as if each were unique.

## Names, emails and phone numbers

Questionnaires are written for applicants and carry little personal data. Email addresses were removed
from the text before it was parsed: each one is replaced with `[email removed]` (about {n_removed:,}
addresses across {n_removed_pages:,} pages, mostly agency help desks and points of contact). That means
`text_sha256` is the hash of the text after removal, not of the page as the portal served it. Phone numbers
were not removed: {p_files:,} of the {tot_text:,} saved pages with text contain one ({len(phones)} distinct
numbers, mostly help desks and agency offices). {s_files} pages contain a Social Security number pattern.

## How it was checked

- Every non-blank line of every parsed page is found again in some parsed field: {n_lost} files with a line
  lost, out of {n_checked:,} USA Staffing files.
- A separate pass counted numbered lines per file and compared with the parser's question count:
  differences are explained by numbered lists kept inside text in all but the
  {n_mis} files above.
- 40 sampled questions were compared with an independent reading of their raw text (number, choice
  count, question text); 39 agreed, and the other was a check artifact: its raw block was cut at 1,500
  characters in the proof file, so the choice count came up short. The proof file is in the repository.

Not checked: the questions against the live portal pages, and whether a question was edited after
the page was read.

## License

The questions are text written by federal agencies for a federal hiring process. I did not find the
portals' terms of use, and I do not assert a license for the text beyond that. Check the sources
before reuse: https://apply.usastaffing.gov and https://jobs.monstergovt.com. The code is MIT.

## Code

The parser, the checks and the backfill workflow: https://github.com/abigailhaddad/usajobs-questionnaires
"""
    out = R / "README.md"
    out.write_text(card)
    print("wrote", out, f"({len(card):,} chars)")


if __name__ == "__main__":
    main()
