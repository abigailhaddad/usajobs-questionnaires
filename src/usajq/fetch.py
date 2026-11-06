"""Fetch questionnaire pages politely and keep a record of every attempt.

USA Staffing pages are a JavaScript app, so they are loaded in Playwright's own headless
Chromium, unmodified: its default user agent, no flags that hide automation, no header changes.
Monster preview pages are plain HTML and are fetched with a plain, honest User-Agent.

Rules this module follows:
* A 403, a 429, a captcha or a bot-defense page stops the whole run at once. Nothing retries
  around it. The run exits with code 3 and the outcome is written to the state file.
* Every attempt is appended to the state file (ok, not_found, blocked, error), so no id is
  fetched twice by accident, and a run can stop and resume.
* A daily request budget (config.MAX_REQUESTS_PER_DAY), a small worker count, and random
  delays between requests.
"""
import asyncio
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config

BLOCK_MARKERS = (
    "captcha", "access denied", "unusual traffic", "verify you are human", "verify you are a human",
    "request blocked", "are you a robot", "too many requests", "rate limit",
)
NOT_FOUND_MARKERS = (
    "questionnaire not found", "no longer available", "does not exist", "invalid questionnaire",
    "page not found", "404 - page not found",
)
# The page first shows a skeleton: the labels ("Position Title", "Agency", ...) with "Loading..." under
# them, about 220 characters. Waiting for a label is not enough. The content has arrived when "Loading..."
# is gone, the page has real text, and the header fields (position title and so on) have values, or when
# the app has put up one of its own error messages. The header can fill in a moment after the questions.
# A page that never gets header values simply waits out the timeout and is read as it is.
RENDERED_JS = (
    "document.body && (function(){var t=document.body.innerText||'';"
    "if(/captcha|access denied|unusual traffic|verify you are/i.test(t))return true;"
    "if(/encountered an error|not found|no longer available/i.test(t))return true;"
    "var head=/Position Title\\s+(?!Agency\\b)\\S/.test(t);"
    "return t.indexOf('Loading...')===-1 && t.length>600 && head;})()"
)
EXIT_BLOCKED = 3
EXIT_NO_CONTENT = 4
# A run whose first attempts all come back without any questionnaire is not working. Stop and look.
BREAKER_AFTER = int(os.environ.get("UQ_BREAKER_AFTER", "8"))
HEADED = os.environ.get("UQ_HEADED", "") not in ("", "0", "false")


def breaker_tripped(counts, after=None):
    """True when enough attempts have run and none has returned (or confirmed missing) a questionnaire."""
    after = BREAKER_AFTER if after is None else after
    total = sum(counts.values())
    return total >= after and counts.get("ok", 0) == 0 and counts.get("not_found", 0) == 0


class Blocked(Exception):
    """The site refused us. Stop the run."""


class NoContent(Exception):
    """Every early attempt came back without a questionnaire. The method is not working."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def usastaffing_url(qid: str) -> str:
    return f"https://apply.usastaffing.gov/ViewQuestionnaire/{qid}"


def monster_preview_url(url: str):
    """Rebuild the preview-questions URL from any Monster questionnaire link, or None."""
    u = urlparse(url)
    if "monstergovt.com" not in u.netloc:
        return None
    seg = [s for s in u.path.split("/") if s]
    if not seg:
        return None
    q = parse_qs(u.query)
    org = (q.get("O") or q.get("orgId") or [None])[0]
    jnum = (q.get("J") or q.get("jnum") or [None])[0]
    if not (org and jnum):
        return None
    return f"https://{u.netloc}/{seg[0]}/vacancy/previewVacancyQuestions.hms?orgId={org}&jnum={jnum}"


def classify_text(status, text):
    """Decide what a response was. Returns (outcome, note)."""
    low = (text or "").lower()
    if status in (403, 429):
        return "blocked", f"http {status}"
    if status and status >= 500:
        return "error", f"http {status}"
    if any(m in low for m in BLOCK_MARKERS):
        return "blocked", "block marker in page"
    if status == 404:
        return "not_found", "http 404"
    if "position title" in low and "announcement number" in low and len(text) >= 500:
        return "ok", ""
    if any(m in low for m in NOT_FOUND_MARKERS):
        return "not_found", "page says not found"
    if "has encountered an error" in low:
        return "error", "app error page"  # retried once by State.done, then left
    if "loading..." in low:
        return "error", "page still loading when read"
    return "error", "no questionnaire content"


class State:
    """Append-only record of attempts, one JSON object per line."""

    def __init__(self, path: Path = None):
        self.path = Path(path or config.STATE_FILE)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.latest = {}
        self.times = []
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                self.latest[(rec["portal"], rec["id"])] = rec
                self.times.append(rec["ts"])

    def done(self, portal, qid, retry_errors=2):
        rec = self.latest.get((portal, qid))
        if not rec:
            return False
        if rec["outcome"] in ("ok", "not_found"):
            return True
        if rec["outcome"] == "error":
            return rec.get("attempts", 1) >= retry_errors
        return False

    def add(self, portal, qid, outcome, **extra):
        prev = self.latest.get((portal, qid), {})
        rec = {"portal": portal, "id": qid, "outcome": outcome, "ts": now(),
               "attempts": prev.get("attempts", 0) + 1, **extra}
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        self.latest[(portal, qid)] = rec
        self.times.append(rec["ts"])
        return rec

    def requests_today(self):
        today = datetime.now(timezone.utc).date().isoformat()
        return sum(1 for t in self.times if t.startswith(today))


def todays_budget(state: State, limit=None):
    left = max(0, config.MAX_REQUESTS_PER_DAY - state.requests_today())
    return min(left, limit) if limit else left


async def fetch_usastaffing(items, raw_dir: Path, state: State, workers=None, delay=None):
    """items: list of (qid, url). Returns a dict of outcome counts. Raises Blocked on a refusal."""
    from playwright.async_api import async_playwright

    workers = workers or config.WORKERS
    lo, hi = delay or (config.DELAY_MIN_SECONDS, config.DELAY_MAX_SECONDS)
    raw_dir.mkdir(parents=True, exist_ok=True)
    counts = {"ok": 0, "not_found": 0, "error": 0, "blocked": 0}
    queue = asyncio.Queue()
    for it in items:
        queue.put_nowait(it)
    stop = asyncio.Event()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not HEADED)  # Playwright's own Chromium, default flags

        async def worker(n):
            context = await browser.new_context()
            page = await context.new_page()

            async def route(r):
                if r.request.resource_type in ("image", "media", "font"):
                    await r.abort()
                else:
                    await r.continue_()

            await page.route("**/*", route)
            while not stop.is_set():
                try:
                    qid, url = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                status, text, note = None, "", ""
                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT_MS)
                    status = resp.status if resp else None
                    if status == 200:
                        try:
                            await page.wait_for_function(RENDERED_JS, timeout=config.RENDER_WAIT_MS)
                        except Exception:
                            pass
                    text = await page.inner_text("body", timeout=10000)
                except Exception as e:  # timeouts and navigation errors are not refusals
                    note = f"{type(e).__name__}: {str(e)[:80]}"
                outcome, why = classify_text(status, text)
                if note and outcome == "error":
                    why = note
                if outcome == "ok":
                    (raw_dir / f"usastaffing_{qid}.txt").write_text(text, encoding="utf-8")
                extra = {} if outcome == "ok" else {"snippet": text[:300]}
                state.add("usastaffing", qid, outcome, url=url, http_status=status, n_chars=len(text), note=why, **extra)
                counts[outcome] += 1
                if outcome == "blocked":
                    stop.set()
                    break
                if breaker_tripped(counts):
                    stop.set()
                    break
                await asyncio.sleep(random.uniform(lo, hi))
            await context.close()

        await asyncio.gather(*(worker(i) for i in range(workers)))
        await browser.close()
    if counts["blocked"]:
        raise Blocked(f"blocked after {sum(counts.values())} requests")
    if breaker_tripped(counts):
        raise NoContent(f"{sum(counts.values())} requests, none returned a questionnaire")
    return counts


def fetch_monster(items, raw_dir: Path, state: State, delay=None):
    """items: list of (jnum, original_url). Plain requests, one at a time."""
    import requests

    lo, hi = delay or (config.DELAY_MIN_SECONDS, config.DELAY_MAX_SECONDS)
    raw_dir.mkdir(parents=True, exist_ok=True)
    counts = {"ok": 0, "not_found": 0, "error": 0, "blocked": 0}
    for jnum, orig in items:
        url = monster_preview_url(orig)
        if not url:
            state.add("monster", jnum, "error", url=orig, note="cannot build a preview url")
            counts["error"] += 1
            continue
        status, text, note = None, "", ""
        try:
            r = requests.get(url, headers={"User-Agent": config.HTTP_USER_AGENT}, timeout=30)
            status = r.status_code
            body = re.sub(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", " ", r.text, flags=re.S)
            text = " ".join(re.sub(r"<[^>]+>", " ", body).split())
        except Exception as e:
            note = f"{type(e).__name__}: {str(e)[:80]}"
        if status == 200 and len(text) >= 1000 and "Vacancy Questions" in text:
            outcome, why = "ok", ""
        else:
            outcome, why = classify_text(status, text)
            if outcome == "ok":  # the USA Staffing markers do not apply here
                outcome, why = "error", "no questionnaire content"
        if note and outcome == "error":
            why = note
        if outcome == "ok":
            (raw_dir / f"monster_{jnum}.txt").write_text(text, encoding="utf-8")
        state.add("monster", jnum, outcome, url=url, http_status=status, n_chars=len(text), note=why)
        counts[outcome] += 1
        if outcome == "blocked":
            raise Blocked("monster refused")
        time.sleep(random.uniform(lo, hi))
    return counts
