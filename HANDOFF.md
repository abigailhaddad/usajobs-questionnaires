# Handoff

For whoever keeps this going. It does three jobs: list the questionnaire ids, fetch the pages, and
publish them as a dataset.

## Scope

**2025 to present.** The dataset covers questionnaires from announcements first seen in 2025 or later
(`config.MIN_YEAR`, override with `UQ_MIN_YEAR`). Earlier years are not planned. An earlier scouting pass
counted about 2.0 million USA Staffing ids from 2017 to 2024 that are not collected. At the polite budget
that is about 673 days of fetching, the announcement text links only 62% to 81% of questionnaires, Monster
links stop appearing in announcement text after 2018, and agency-run portals block automation. If someone
wants to go back, `scripts/backfill.py --years 2023` fetches one year, and the same method renders pages from
2019 to 2024 (see "The fetch method").

## What exists

| Piece | State |
|---|---|
| Parser (USA Staffing pages to questions) | Done, tested, checked against 49,868 real pages |
| 2025 release (52,227 questionnaires, 949,370 questions) | Published at `abigailhaddad/usajobs-questionnaires`, emails removed |
| Id inventory | Done: 2,337,708 ids from the announcement dataset |
| Fetching 2025-26 pages | Works (see "The fetch method") |
| Backfill workflow | Scheduled daily at 06:17 UTC; a 50-request test on a GitHub runner published a batch |

## The fetch method

USA Staffing pages are a JavaScript app. A plain request returns a 2,115-byte shell, so the fetcher loads
each page in Playwright's own headless Chromium with its default flags and user agent: no stealth plugins,
no header changes, nothing that hides automation.

**What went wrong in the first pilot, and the fix.** The first pilot fetched 40 pre-2025 ids and every
one came back as 222 characters. That text was the page's loading skeleton: the labels "Position Title",
"Agency" and "Announcement Number" with "Loading..." under them. The fetcher waited until the words
"Position Title" appeared, and the skeleton already contains them, so it read the page too early. It now
waits until "Loading..." is gone and the page has real text (up to 30 seconds, `UQ_RENDER_WAIT_MS`), or
until the app shows its own error message. Browser flags and the user agent had nothing to do with it.

**Checks of the fix.** 10 of 10 ids first seen in 2025 H2 and 2026 rendered in plain headless Chromium, with
full text in 1 to 4 seconds. Of 10 ids first seen in 2019 to 2024, 9 rendered, so old questionnaires persist;
one 2019 id returned USA Staffing's own "has encountered an Error" page. The fixed fetcher then got 3 of 3
on new ids.

**The first batch (2026-11-06).** 300 ids, 150 first seen in 2025 and 150 in 2026, spread across the year.
300 of 300 returned a questionnaire (no `not_found`, `error` or `blocked`), in 19 minutes 46 seconds with
2 workers and 4 to 9 seconds between requests: about 15 a minute, 910 an hour. 290 parsed `ok` and 10
parsed `ok_missing_header`: the labels were there but the position title, agency and announcement number
were blank, because the page body finishes a moment before the header values. The wait now also requires
the header values. I re-fetched those 10 ids and all 10 came back with headers, so the batch is 300 `ok`.
Nine pages had an email address, now `[email removed]`. The batch built 300 questionnaires, 5,982 questions
and 877 sections, none of its ids were already published, and the publish dry run passes.

The fetcher saves a 300-character snippet of any page that is not a questionnaire (the `snippet` field in
`state/attempts.jsonl`), classifies the app's error page as `error` (retried once, then left), and stops
after 8 attempts if none has worked (exit code 4).

## Rules the fetcher follows

- Any 403, 429, captcha or bot-defense text stops the run at once (exit code 3). Nothing retries around it.
- Every attempt goes in `state/attempts.jsonl`. An id is not fetched again once it is `ok` or
  `not_found`. An `error` is retried once more. A `blocked` is never marked done.
- Budget: 3,000 requests a day, 2 workers, 4 to 9 seconds between requests (`config.py`; override
  with `UQ_MAX_REQUESTS_PER_DAY`, `UQ_WORKERS`, `UQ_DELAY_MIN`, `UQ_DELAY_MAX`).
- At that budget the remaining 2025 and 2026 ids (about 251,000: 83,006 from 2025 and 168,473 from 2026)
  take about 84 days. The measured rate is about 910 pages an hour, so a 3,000-request day is about
  3 hours 20 minutes of fetching. New announcements add about 19,000 ids a month, so keeping up with
  them is about 630 a day, about 42 minutes. Faster means more load on the site. The scouting agent
  read, in Protect Democracy's notes for a similar project, that USA Staffing refused a runner after about
  1,700 requests at 4 workers. I have not verified that or tested what this project tolerates (the batch
  above was 300 requests).

## What the inventory is

`data/id_inventory.parquet`: one row per questionnaire found in the text of an announcement in
`abigailhaddad/usajobs-scraping`. Columns: portal, questionnaire_id, first_seen_month,
n_announcements, control_number, url (Monster only). `data/inventory_by_year.csv` has counts by year.
`data/announcement_link_rates.parquet` has, by month, how many announcements there were and how
many linked a questionnaire: about 62% in 2018, 70% in 2019, 73% in 2020, 76% in 2021, 78% in 2022,
81% in 2023, 79% in 2024. Before mid-2017 it is under 30%.

Gaps:

- **Monster.** Monster links show up in announcement text only through 2018 (17,395 ids). After
  that the announcement text has no Monster link, although Monster postings exist (2,536 in June 2023
  alone). The 2025 set got its Monster links from an apply-URL field the historical dataset does not
  have. Pre-2025 Monster questionnaires are mostly not recoverable this way.
- **Other systems.** Agency-run portals and systems like Workday are not covered.
- **Announcements with no questionnaire link** are not in the inventory at all.
- Rebuild it with `python scripts/inventory.py` then `--combine` (about 25 minutes, reads over HTTPS,
  downloads nothing large).

## Secrets and variables (GitHub Actions)

| Name | What for |
|---|---|
| `HF_TOKEN` (secret) | Publishing to Hugging Face. Without it the workflow builds the batch and does not publish, and the run goes red. |
| `UQ_HF_DATASET` (variable) | The dataset id. Default `abigailhaddad/usajobs-questionnaires`. |
| `UQ_MAX_REQUESTS_PER_DAY` (variable) | Daily budget. Default 3000. |
| `UQ_HEADED` (variable) | Set to `1` to run Chromium headed under xvfb. |

Every place that names the current owner: `src/usajq/config.py` (dataset id, announcement dataset),
`.github/workflows/backfill.yml` (the default dataset id), `README.md`, and the card text in
`scripts/make_card.py` (the repository link, "to be created").

## The workflow

`.github/workflows/backfill.yml` runs daily at 06:17 UTC and can also be started by hand
(`workflow_dispatch`). A run: tests, list published ids from Hugging Face, fetch a batch, build the batch tables,
run the health check, publish one commit if healthy, commit the state file. It always reaches the
health check and the state commit, and ends red on any of: exit 3 (refused), exit 4 (nothing came
back), a failed health check, or no `HF_TOKEN`.

`src/usajq/health.py` fails the run if there were no attempts, if any request was refused today, if
fewer than half of the last 200 attempts returned a questionnaire or a clear not-found, if every
attempt today was an error, or if fewer than 90% of a batch's pages parsed (a layout change).

Each batch adds files (`data/<table>/part-<tag>.parquet`) and never rewrites old ones. The publisher
refuses a batch whose ids are already published.

## Publishing

The 2025 release is published (one commit, `data/<table>/part-2025-release.parquet`). Each batch adds
`part-<tag>.parquet` files and never rewrites old ones:

1. `python scripts/published_ids.py` (writes `build/have.csv`).
2. `python scripts/backfill.py --limit 2500 --have build/have.csv --raw-dir build/raw`
3. `python scripts/build_release.py build/raw "" --out build/batch --method live --state state/attempts.jsonl`
4. `python scripts/publish_to_hf.py --release build/batch --tag batch-<date> --no-card` (dry run),
   then the same with `--upload`.

The first batches: 300 questionnaires built locally (not uploaded), then a 50-request test on a GitHub
runner that published `batch-2026-11-06T2109` (50 questionnaires, 865 questions) to Hugging Face. The
repo is public at github.com/abigailhaddad/usajobs-questionnaires.

Email addresses are replaced with `[email removed]` before parsing (`src/usajq/redact.py`), so
`text_sha256` is the hash of the text after removal.

## Tests and checks

`python -m pytest -q` (39 tests, no network). `python scripts/verify_parse.py RAW_DIR` re-checks the
parser against raw pages: every body line must be found again in some parsed field, and numbered
lines must account for the question count. `evidence/parse_verify.json` lists the 46 files (0.09%)
where a numbered line is ambiguous.

## Known limits of the parser

- A numbered list inside a question's own text can look like another question. The parser keeps it
  as text unless the numbers run in order.
- A note between two questions is kept in the previous question's `trailing_text`.
- Monster pages are one line of text and are not split into questions.
- Scoring and "required" are not on the preview pages, so they are not columns.
- A page whose layout changes will parse as `no_questions` or lose structure. The health check
  watches the parse share.
