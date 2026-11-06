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
- **2025 release:** published.
- **Inventory:** 2.3 million questionnaire ids found in announcement text, 2017 to 2026, in
  `data/id_inventory.parquet`. In scope: about 251,000 USA Staffing ids from 2025 and 2026 that are not
  collected yet, about 84 days at the polite budget.
- **Fetching:** works. The first pilot failed because the fetcher read the page while it was still
  loading; that is fixed (HANDOFF.md, "The fetch method"). A 300-id batch returned 300 questionnaires.
  A 50-request test on a GitHub runner published a batch to Hugging Face, and the daily workflow is scheduled.

## Layout

    src/usajq/        parse_usastaffing.py  the parser
                      fetch.py              polite fetching, state file, refusal handling
                      health.py             post-run checks
                      config.py             every setting, each overridable by an UQ_* variable
    scripts/          inventory.py          list questionnaire ids from the announcement dataset (reads over HTTPS)
                      backfill.py           fetch a bounded batch
                      build_release.py      raw pages -> questionnaires, questions, sections (Parquet)
                      make_card.py          write the dataset card from the built tables
                      publish_to_hf.py      one Hugging Face commit, dry run by default
                      verify_parse.py       check the parser against the raw pages, a second way
    data/             id_inventory.parquet, announcement_link_rates.parquet, inventory_by_year.csv,
                      collected_ids_2025_release.csv
    state/            attempts.jsonl        every fetch attempt, one line each
    evidence/         the parser's spot check and verification results
    tests/            pytest, no network

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
