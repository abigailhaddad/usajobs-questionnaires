# Handoff

## What this is

Every USAJOBS questionnaire from 2025 on, split into questions. Code: [github.com/abigailhaddad/usajobs-questionnaires](https://github.com/abigailhaddad/usajobs-questionnaires). Data: [Hugging Face dataset](https://huggingface.co/datasets/abigailhaddad/usajobs-questionnaires) (the card lists the columns and limits). Site: [usajobs-questionnaires.abigailhaddad.com](https://usajobs-questionnaires.abigailhaddad.com).

## What runs on its own

`.github/workflows/backfill.yml` runs daily (the schedule is at the top of the file). Each run refreshes the id inventory, fetches a polite batch of questionnaires (up to 2,500 requests, two at a time, with pauses), publishes the batch to Hugging Face as one commit and saves its state in the repo. In a normal week you do nothing.

About 250,000 ids were still to fetch on 2026-11-06, roughly 100 days at that rate. Scope is 2025 on (`UQ_MIN_YEAR` in `src/usajq/config.py`). The README says why earlier years aren't planned.

## Secrets and variables (Actions)

- `HF_TOKEN` (secret): write access to the dataset. Without it the run builds the batch, publishes nothing and ends red.
- `UQ_HF_DATASET` (variable, optional): the dataset id. Default `abigailhaddad/usajobs-questionnaires`.
- `UQ_MAX_REQUESTS_PER_DAY` (variable, optional): the daily cap. Default 3000.
- `UQ_HEADED` (variable, optional): set to `1` to run the browser headed under a virtual display.

## If you take it over

- Find the owner's names with `grep -rn abigailhaddad .` They are mostly in `src/usajq/config.py` (the two dataset ids), the default in `backfill.yml`, `scripts/make_card.py` (the repo link in the card) and the README.
- The ids come from the announcement dataset `abigailhaddad/usajobs-scraping`, which the `usajobs_historical` repo publishes. To use your own, set `UQ_ANNOUNCEMENTS` (add it to the workflow's `env`).
- Create a GitHub repo and a Hugging Face token with write access. The first publish creates the dataset, public, if it doesn't exist.
- Copy the published dataset first. An empty dataset starts without the 52,227 questionnaires from the 2025 release, and the fetcher treats those ids as already collected (`data/collected_ids_2025_release.csv`), so they would never be filled in.

## When it breaks

- A red run in the Actions tab is the signal. `scripts/health.py` (rules in `src/usajq/health.py`) fails the run when there were no attempts, the site refused a request, fewer than half of the last 200 attempts succeeded, or under 90% of a batch parsed.
- Every fetch attempt is one line in `state/attempts.jsonl`. A page that isn't a questionnaire keeps a short `snippet`.
- To rerun by hand: Actions, Backfill questionnaires, Run workflow (input `limit`).
- Exit 3 means the site refused a request (a 403 or 429). The fetcher stops at the first one and the run ends red. Don't retry harder. Wait, and read the site's terms of use, which I haven't found. Exit 4 means nothing that looks like a questionnaire came back, so the fetch method needs attention.

## Costs

None. No model is called.
