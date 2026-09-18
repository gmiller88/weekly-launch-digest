"""Cross-week memory: what we've already covered, and how we scored it.

Persisted to data/history.json and committed by the weekly workflow so each run
starts with the prior weeks in context instead of cold.
"""

import json
import os
from datetime import datetime

HISTORY_PATH = "data/history.json"

# How many prior weeks to feed into the prompts.
_CONTEXT_WEEKS = 8

# A launch stays on the exclusion list this long. Long enough to stop the same
# announcement resurfacing on re-reported news, short enough that a genuine
# follow-up launch from the same company can still qualify.
_EXCLUSION_WEEKS = 6


def _key(company: str, launch_name: str = "") -> str:
    return f"{company.strip().lower()}|{launch_name.strip().lower()}"


def load_history(path: str = HISTORY_PATH) -> dict:
    if not os.path.exists(path):
        return {"weeks": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_history(history: dict, path: str = HISTORY_PATH) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
        f.write("\n")


def record_week(history: dict, date: str, launches: dict, funding: dict) -> dict:
    """Append this run to the history, replacing any existing entry for the date."""
    week = {
        "date": date,
        "launches": [
            {
                "company": e.get("company", ""),
                "launch_name": e.get("launch_name", ""),
                "score": e.get("score"),
                "assessable": e.get("assessable", True),
                # Kept so a launch can be tracked retroactively later.
                "url": (e.get("sources") or [{}])[0].get("url", ""),
            }
            for e in launches.get("entries", [])
        ],
        "funding": [
            {"company": e.get("company", "")} for e in funding.get("entries", [])
        ],
    }
    weeks = [w for w in history.get("weeks", []) if w.get("date") != date]
    weeks.append(week)
    weeks.sort(key=lambda w: w.get("date", ""))
    return {"weeks": weeks}


def _recent_weeks(history: dict, n: int) -> list[dict]:
    return history.get("weeks", [])[-n:]


def launch_exclusions(history: dict) -> list[str]:
    """Company|launch keys covered recently enough that we shouldn't repeat them."""
    keys = []
    for week in _recent_weeks(history, _EXCLUSION_WEEKS):
        for item in week.get("launches", []):
            keys.append(_key(item.get("company", ""), item.get("launch_name", "")))
    return keys


def funding_exclusions(history: dict) -> list[str]:
    """Companies whose round we've already written up in recent weeks."""
    names = []
    for week in _recent_weeks(history, _EXCLUSION_WEEKS):
        for item in week.get("funding", []):
            name = item.get("company", "").strip()
            if name:
                names.append(name)
    return sorted(set(names), key=str.lower)


def coverage_block(history: dict) -> str:
    """Prior weeks rendered for the prompt, so the model can see its own trend line."""
    weeks = _recent_weeks(history, _CONTEXT_WEEKS)
    if not weeks:
        return "(No prior weeks on record — this is the first run with history enabled.)"

    lines = []
    for week in weeks:
        lines.append(f"Week ending {week.get('date', '?')}:")
        for item in week.get("launches", []):
            score = item.get("score")
            label = f"{score}/10" if score is not None else "not assessable"
            company = item.get("company", "?")
            launch = item.get("launch_name", "")
            lines.append(f"  - [{label}] {company} — {launch}")
        if not week.get("launches"):
            lines.append("  - (no qualifying launches)")
    return "\n".join(lines)


def score_history(history: dict) -> list[float]:
    scores = []
    for week in history.get("weeks", []):
        for item in week.get("launches", []):
            if isinstance(item.get("score"), (int, float)):
                scores.append(float(item["score"]))
    return scores


def today_str() -> str:
    return datetime.now().strftime("%B %d, %Y")


def today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")
