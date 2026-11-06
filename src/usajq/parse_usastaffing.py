"""Turn the text of a USA Staffing questionnaire preview page into questions.

The input is the page's visible text (what a reader sees), saved as is. The page has a header
(position title, agency, announcement number, open period), then blocks under headings
(Eligibilities, Preferences, Conditions of Employment, Assessment 1, 2, ...), then a site footer.

Within a block a question starts with "N. ", and its answer choices are lines starting with
"A. ", "B. " and so on. Lines in between are either more question text or follow-up fields.

Everything is deterministic. Nothing is guessed, and a file that does not look like a
questionnaire gets a parse_status that says why, with no questions.
"""
import hashlib
import re
from datetime import datetime

HEADER_LABELS = ("Position Title", "Agency", "Announcement Number", "Open Period")
BANNER = "For preview purposes only"
FIXED_SECTIONS = {
    "eligibilities": "eligibility",
    "preferences": "preference",
    "conditions of employment": "conditions",
}
ASSESSMENT_RE = re.compile(r"^Assessment (\d+)$")
QUESTION_RE = re.compile(r"^(\d+)\.\s+(\S.*)$")
NUMBER_ALONE_RE = re.compile(r"^(\d+)\.\s*$")  # some pages put the number on its own line
OPTION_RE = re.compile(r"^\s*([A-Z])\.\s+(\S.*)$")
OPTION_EMPTY_RE = re.compile(r"^\s*([A-Z])\.\s*$")
MULTI_RE = re.compile(r"select all|check all|all that apply|mark all", re.I)
DATE_RE = re.compile(r"([A-Z][a-z]+day, [A-Z][a-z]+ \d{1,2}, \d{4})")

LOGIN_MARKERS = (
    "An official website of the United States government Here's how you know",
    "Your Session is About to Expire",
)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _footer_start(lines):
    """Index of the first line of the site footer, or len(lines)."""
    for i, line in enumerate(lines):
        if line.strip().endswith("Terms of Use") and any("FOIA" in x for x in lines[i + 1 : i + 3]):
            return i
    for i, line in enumerate(lines):
        if re.match(r"^©\s*\d{4} US Office of Personnel Management", line.strip()):
            return i
    return len(lines)


def _parse_date(s):
    try:
        return datetime.strptime(s, "%A, %B %d, %Y").date().isoformat()
    except ValueError:
        return None


def _header(lines):
    """Read the four header fields. Returns (fields, index of the first body line)."""
    fields = {}
    i = 0
    n = len(lines)
    while i < n and len(fields) < len(HEADER_LABELS):
        label = lines[i].strip()
        if label in HEADER_LABELS and label not in fields:
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n:
                fields[label] = lines[j].strip()
            i = j + 1
        elif label.startswith(BANNER) or not label or label == "Opens in new window":
            i += 1
        else:
            break
    while i < n and (not lines[i].strip() or lines[i].strip().startswith(BANNER) or lines[i].strip() == "Opens in new window"):
        i += 1
    return fields, i


def _classify(options, dropdown, text, trailing):
    if options:
        return "multi_choice" if MULTI_RE.search(text) else "single_choice"
    if dropdown:
        return "dropdown"
    return "free_text"


def parse(text: str) -> dict:
    """Parse one questionnaire. Returns a dict with header fields, sections and questions."""
    out = {
        "parse_status": "ok",
        "position_title": None,
        "agency": None,
        "announcement_number": None,
        "open_period": None,
        "open_date": None,
        "close_date": None,
        "preview_banner": BANNER in text,
        "sections": [],
        "questions": [],
    }
    stripped = text.lstrip()
    if stripped.startswith("<!DOCTYPE") or stripped.startswith("<html"):
        out["parse_status"] = "html_shell"
        return out
    if any(m in text for m in LOGIN_MARKERS) and "Position Title" not in text:
        out["parse_status"] = "login_page"
        return out
    lines = text.replace("\r\n", "\n").split("\n")
    if "Position Title" not in text[:200]:
        out["parse_status"] = "not_a_questionnaire"
        return out

    fields, body_start = _header(lines)
    out["position_title"] = fields.get("Position Title")
    out["agency"] = fields.get("Agency")
    anno = fields.get("Announcement Number")
    if anno:
        anno = re.sub(r"\s*Opens in new window\s*$", "", anno)
    out["announcement_number"] = anno
    out["open_period"] = fields.get("Open Period")
    if out["open_period"]:
        dates = DATE_RE.findall(out["open_period"])
        if dates:
            out["open_date"] = _parse_date(dates[0])
            out["close_date"] = _parse_date(dates[-1]) if len(dates) > 1 else None

    end = _footer_start(lines)
    body = lines[body_start:end]

    section = None
    kind = None
    block = 0
    intro = []
    q = None
    expected_q = None
    expected_opt = "A"
    qn_in_section = 0

    def close_section():
        if section is not None:
            out["sections"].append(
                {"block_index": block, "section": section, "section_kind": kind,
                 "intro_text": "\n".join(intro).strip() or None}
            )

    def close_question():
        nonlocal q
        if q is None:
            return
        q["question_text"] = "\n".join(q.pop("_text")).strip()
        q["trailing_text"] = "\n".join(q.pop("_trail")).strip() or None
        q["raw_block"] = "\n".join(q.pop("_raw")).rstrip()
        q["question_type"] = _classify(q["options"], q["has_dropdown"], q["question_text"], q["trailing_text"])
        q["n_options"] = len(q["options"])
        out["questions"].append(q)
        q = None

    for line in body:
        s = line.strip()
        key = s.lower()
        new_section = None
        if key in FIXED_SECTIONS:
            new_section = (s, FIXED_SECTIONS[key])
        else:
            m = ASSESSMENT_RE.match(s)
            if m:
                new_section = (s, "assessment")
        if new_section is not None:
            close_question()
            close_section()
            section, kind = new_section
            block += 1
            intro = []
            expected_q = None  # numbering can continue from an earlier block, so the first number is free
            qn_in_section = 0
            continue

        qm = None
        alone = False
        if not line.startswith(" "):
            qm = QUESTION_RE.match(s)
            if qm is None:
                qm = NUMBER_ALONE_RE.match(s)
                alone = qm is not None
        starts_question = False
        if qm:
            num = int(qm.group(1))
            if expected_q is None or num == expected_q or (num == 1 and q is not None and (q["options"] or q["has_dropdown"])):
                starts_question = True
        if starts_question:
            close_question()
            num = int(qm.group(1))
            qn_in_section += 1
            q = {
                "block_index": block or 1,
                "section": section,
                "section_kind": kind,
                "question_number": num,
                "options": [],
                "options_lettered": True,
                "has_dropdown": False,
                "_text": [] if alone else [qm.group(2).strip()],
                "_trail": [],
                "_raw": [line],
            }
            expected_q = num + 1
            expected_opt = "A"
            continue

        if q is None:
            if section is None and not s:
                continue
            if section is None:
                # text before any heading: keep it with a synthetic section so nothing is lost
                section, kind, block = "(no heading)", "unknown", max(block, 1)
            intro.append(line.rstrip())
            continue

        q["_raw"].append(line)
        om = OPTION_RE.match(line)
        oe = OPTION_EMPTY_RE.match(line)
        if (om or oe) and (om or oe).group(1) == expected_opt:
            letter = (om or oe).group(1)
            q["options"].append({"letter": letter, "text": (om.group(2).strip() if om else "")})
            expected_opt = chr(ord(letter) + 1) if letter < "Z" else "Z"
            continue
        if s == "--Select--":
            q["has_dropdown"] = True
            continue
        if not s:
            continue
        if (line.startswith(" ") and q["_text"] and not q["_trail"] and len(s) < 300
                and all(not o.get("lettered", True) for o in q["options"])):
            # Choices with no letters (a Yes / No pair, for example): number them in page order.
            q["options_lettered"] = False
            q["options"].append({"letter": chr(ord("A") + min(len(q["options"]), 25)), "text": s, "lettered": False})
            continue
        if q["options"] or q["has_dropdown"]:
            # After the choices begin: a follow-up field, or a note that sits before the next question.
            # The page text keeps each choice on one line, so none of this is a wrapped choice.
            q["_trail"].append(s)
        else:
            q["_text"].append(s)
    close_question()
    close_section()

    if not out["questions"]:
        out["parse_status"] = "no_questions"
    elif not out["announcement_number"]:
        out["parse_status"] = "ok_missing_header"
    return out
