# USAJOBS questionnaires

Every USAJOBS questionnaire we can recover, split into questions. The questionnaires are the eligibility,
preference, conditions-of-employment and assessment questions an applicant answers before a resume is
rated. They live on USA Staffing (`apply.usastaffing.gov/ViewQuestionnaire/<id>`) and Monster preview
pages, and they carry no applicant answers.

The published dataset is `abigailhaddad/usajobs-questionnaires` on Hugging Face. The first release is the
2025 collection: 52,227 questionnaires, 949,370 questions, with email addresses removed. Scope is 2025 to
present. The remaining 2025 and 2026 questionnaires are collected in daily batches. Earlier years are not
planned (see HANDOFF.md for why).

## Where it stands

- **Parser:** done and checked. See `evidence/` and the dataset card.
- **Dataset:** the 2025 release (52,227 questionnaires, 949,370 questions) is published, and the daily workflow adds a batch each run.
- **Inventory:** about 2.3 million questionnaire ids found in announcement text, 2017 to 2026, in
  `data/id_inventory.parquet`, plus a small update file each day for ids announced since. About 250,000
  USA Staffing ids from 2025 and 2026 were not collected on 2026-11-06.
- **Fetching:** works, and runs daily on GitHub Actions. See `HANDOFF.md` for running and taking it over.

## Layout

    src/usajq/        parse_usastaffing.py  the parser
                      fetch.py              polite fetching, state file, refusal handling
                      health.py             post-run checks
                      config.py             every setting, each overridable by an UQ_* variable
    scripts/          inventory.py          list questionnaire ids from the announcement dataset (reads over HTTPS);
                                            --update adds the new ones daily
                      backfill.py           fetch a bounded batch
                      build_release.py      raw pages -> questionnaires, questions, sections (Parquet)
                      make_card.py          write the dataset card from the built tables
                      publish_to_hf.py      one Hugging Face commit, dry run by default
                      verify_parse.py       check the parser against the raw pages, a second way
    data/             id_inventory.parquet, id_inventory_updates/, announcement_link_rates.parquet, inventory_by_year.csv,
                      collected_ids_2025_release.csv
    state/            attempts.jsonl        every fetch attempt, one line each
    evidence/         the parser's spot check and verification results
    tests/            pytest, no network

## How it works

**Fetching.** USA Staffing pages are a JavaScript app, and a plain request returns a 2,115-byte shell. The fetcher
loads each page in Playwright's own headless Chromium with its default flags and user agent: no stealth
plugins, no header changes. It waits until "Loading..." is gone and the header values appear (up to 30 seconds,
`UQ_RENDER_WAIT_MS`). An early version read the loading skeleton and every page came back as 222 characters.

- Any 403, 429, captcha or bot-defense text stops the run at once (exit 3). Nothing retries around it.
- Every attempt goes in `state/attempts.jsonl`. An id isn't fetched again once it is `ok` or `not_found`. An `error`
  is retried once more. A `blocked` is never marked done.
- Budget (`config.py`, each overridable by a `UQ_*` variable): 2 workers, 4 to 9 seconds between requests,
  3,000 requests a day. A 300-id batch on 2026-11-06 ran at about 910 pages an hour.

**The id inventory.** `scripts/inventory.py` lists every questionnaire id found in the text of an announcement in
`abigailhaddad/usajobs-scraping`. Each daily run calls `--update`, which re-reads the two newest months and writes
new ids to `data/id_inventory_updates/` without touching the base file. To rebuild the base, run
`python scripts/inventory.py`, then `--combine` (about 25 minutes, reads over HTTPS, deletes the update files).

- Monster links show up in announcement text only through 2018, so most pre-2025 Monster questionnaires can't be recovered this way.
- Agency-run portals and systems like Workday aren't covered. Announcements with no questionnaire link aren't in the inventory.
- `data/announcement_link_rates.parquet` has, by month, how many announcements linked a questionnaire: about 62% in 2018 to 81% in 2023.

**Why not earlier years.** About 2.0 million USA Staffing ids from 2017 to 2024 aren't collected, which is about 673 days
of fetching at the budget. Announcement text links only 62% to 81% of questionnaires, Monster links stop after 2018, and
agency-run portals block automation. `python scripts/backfill.py --years 2023` fetches one year if someone wants to try.

**Parser limits.** A numbered list inside a question's text can look like another question, so the parser keeps it as text
unless the numbers run in order. A note between two questions goes into the previous question's `trailing_text`. Monster pages
are one line of text and aren't split into questions. Scoring and "required" aren't on the preview pages, so they aren't columns.
A page whose layout changes parses as `no_questions` or loses structure, which the health check watches. Email addresses are
replaced with `[email removed]` before parsing (`src/usajq/redact.py`), so `text_sha256` hashes the text after removal.
`evidence/parse_verify.json` lists the 46 files (0.09%) where a numbered line is ambiguous.

## Run it

    pip install -r requirements.txt && python -m playwright install chromium
    python -m pytest -q

    # build the release from a folder of saved pages (usastaffing_<id>.txt, monster_<id>.txt)
    python scripts/build_release.py RAW_DIR LINKS_CSV --out build/release
    python scripts/verify_parse.py RAW_DIR
    python scripts/make_card.py
    python scripts/publish_to_hf.py                  # dry run
    python scripts/publish_to_hf.py --upload         # needs HF_TOKEN or a cached login

    # fetch (small, polite, resumable)
    python scripts/backfill.py --limit 300 --years 2026 2025 --per-year 150 --have data/collected_ids_2025_release.csv --dry-run

`backfill.py` exits 3 if the site refuses a request and 4 if nothing that looks like a questionnaire
comes back. Either way it stops. Read HANDOFF.md before running it again.

## License

Code: MIT. The questionnaires are federal agency text. I did not find the portals' terms of use, so the
dataset card does not assert a license for the text. Check the sources before reuse.
