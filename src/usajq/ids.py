"""Portal and id from a questionnaire URL."""
import re

USA_ID = re.compile(r"ViewQuestionnaire/(\d+)")
MON_JNUM = re.compile(r"[?&]jnum=(\d+)", re.I)
MON_J = re.compile(r"[?&]J=(\d+)")


def portal_and_id(url: str):
    """Return (portal, id) for a questionnaire URL, or ("other", None)."""
    if "usastaffing.gov" in url:
        m = USA_ID.search(url)
        return "usastaffing", (m.group(1) if m else None)
    if "monstergovt.com" in url:
        m = MON_JNUM.search(url) or MON_J.search(url)
        return "monster", (m.group(1) if m else None)
    return "other", None
