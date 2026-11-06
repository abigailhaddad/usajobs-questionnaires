# Handoff

For whoever keeps this going. It does three jobs: list the questionnaire ids, fetch the pages, and
publish them as a dataset.

## What exists

| Piece | State |
|---|---|
| Parser (USA Staffing pages to questions) | Done, tested, checked against 49,868 real pages |
| 2025 release (52,227 questionnaires, 949,370 questions) | Built in `build/release`, dry run passes, **not uploaded** |
| Id inventory | Done: 2,337,708 ids from the announcement dataset |
| Fetching | **Not working yet.** See "The pilot" |
| Backfill workflow | Written, not scheduled, never run |

## The pilot

I fetched 40 pre-2025 USA Staffing pages: 8 spread across each of 2018, 2020, 2022, 2023 and 2024,
with 2 workers and 4 to 9 seconds between requests. All 40 came back HTTP 200 with 222 characters of
text and no questionnaire. None was a 403, a 429 or a captcha page. I did not save the text, so I
cannot say what the 222 characters were. The pilot was capped at 40 requests, so I stopped there.

What I know and don't:

- The pages are a JavaScript app. A plain request returns a 2,115-byte shell (found in the earlier
  scouting), so a browser is required.
- Two earlier checks by the scouting agent, in a different browser setup, did show a full questionnaire
  with no login (a 2019 and a 2021 id), so old questionnaires do persist. I did not repeat that.
- This code uses Playwright's own headless Chromium with its default flags and user agent. The
  collection that produced the 2025 pages used a Chrome user agent and launch flags that hide
  automation. I did not copy those. Whether that difference is the cause is unverified.

The fetcher now saves a 300-character snippet of every page that is not a questionnaire (the `snippet`
field in `state/attempts.jsonl`), and stops the run after 8 attempts if none has worked (exit code 4).

**First thing to do:** run 5 or so ids in a visible browser (`UQ_HEADED=1`, on a machine with a display)
and read the snippets. If a visible browser works and headless does not, the site treats headless
Chromium differently. Whether to work around that is a decision for the owner, and the portals' terms
of use are worth reading first (I did not find them).

## Rules the fetcher follows

- Any 403, 429, captcha or bot-defense text stops the run at once (exit code 3). Nothing retries around it.
- Every attempt goes in `state/attempts.jsonl`. An id is not fetched again once it is `ok` or
  `not_found`. An `error` is retried once more. A `blocked` is never marked done.
- Budget: 3,000 requests a day, 2 workers, 4 to 9 seconds between requests (`config.py`; override
  with `UQ_MAX_REQUESTS_PER_DAY`, `UQ_WORKERS`, `UQ_DELAY_MIN`, `UQ_DELAY_MAX`).
- At that budget the 2.27 million uncollected USA Staffing ids take about 757 days. Of those,
  2.02 million are from 2017 to 2024 (about 673 days). Faster means more load on the site.
  The scouting agent read, in Protect Democracy's notes for a similar project, that USA Staffing refused
  a runner after about 1,700 requests at 4 workers. I have not verified that or tested what this
  project tolerates.

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

`.github/workflows/backfill.yml` is run by hand (`workflow_dispatch`) and has a commented-out
schedule. A run: tests, list published ids from Hugging Face, fetch a batch, build the batch tables,
run the health check, publish one commit if healthy, commit the state file. It always reaches the
health check and the state commit, and ends red on any of: exit 3 (refused), exit 4 (nothing came
back), a failed health check, or no `HF_TOKEN`.

`src/usajq/health.py` fails the run if there were no attempts, if any request was refused today, if
fewer than half of the last 200 attempts returned a questionnaire or a clear not-found, if every
attempt today was an error, or if fewer than 90% of a batch's pages parsed (a layout change).

Each batch adds files (`data/<table>/part-<tag>.parquet`) and never rewrites old ones. The publisher
refuses a batch whose ids are already published.

## Publishing the 2025 release

1. Read `build/release/README.md` (regenerate with `python scripts/make_card.py`).
2. `python scripts/publish_to_hf.py` (dry run, writes nothing).
3. `python scripts/publish_to_hf.py --upload` (one commit, creates the public dataset).
4. Create the GitHub repo and replace "(to be created)" in the card with the link.

## Tests and checks

`python -m pytest -q` (31 tests, no network). `python scripts/verify_parse.py RAW_DIR` re-checks the
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
