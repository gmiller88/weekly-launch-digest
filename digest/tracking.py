"""Post-launch tracking: what happened 4, 8 and 12 weeks after the launch moment.

The weekly scan only ever sees T+0, which biases it toward whatever assets exist
on announcement day. The sustained campaign is where the real GTM lesson lives,
so a tracked launch gets three follow-up checkpoints.

State lives in GitHub issues (created by the "Track this launch" button in the
email) plus data/tracking/<slug>/, which is committed by the workflow. The
baseline snapshot matters most: you cannot diff a landing page you never
captured, and "which 'coming soon' items shipped" is exactly a diff.
"""

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

import anthropic
from tavily import TavilyClient

from .llm import structured

TRACK_LABEL = "track"
TRACKING_DIR = "data/tracking"
CHECKPOINT_WEEKS = (4, 8, 12)
MAX_ACTIVE = 3

_API = "https://api.github.com"


# ── GitHub plumbing ──────────────────────────────────────────────────────


def _token() -> str | None:
    token = os.getenv("GITHUB_TOKEN")
    if token:
        return token
    try:  # local runs: borrow the gh CLI's credential
        return subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return None


def repo_slug() -> str | None:
    """owner/repo, from the Actions env or the git remote."""
    if os.getenv("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return None
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def _api_call(path: str, method: str = "GET", payload: dict | None = None):
    token, repo = _token(), repo_slug()
    if not token or not repo:
        return None
    req = urllib.request.Request(
        f"{_API}/repos/{repo}{path}",
        method=method,
        data=json.dumps(payload).encode() if payload else None,
    )
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if payload:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        print(f"  github {method} {path} -> {e.code} {e.read()[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"  github {method} {path} failed: {e}", file=sys.stderr)
    return None


def track_button_url(entry: dict, digest_date: str) -> str | None:
    """The 'Track this launch' link for one digest entry.

    Opens a pre-filled new issue; the reader just presses Submit.
    """
    repo = repo_slug()
    if not repo:
        return None

    payload = {
        "company": entry.get("company", ""),
        "launch_name": entry.get("launch_name", ""),
        "anchor_date": digest_date,
        "original_score": entry.get("score"),
        "url": (entry.get("sources") or [{}])[0].get("url", ""),
    }
    body = (
        "Tracking this launch for 4-, 8- and 12-week GTM follow-up.\n\n"
        "Press **Submit new issue** — no edits needed.\n\n"
        "```json\n" + json.dumps(payload, indent=2) + "\n```\n"
    )
    query = urllib.parse.urlencode({
        "labels": TRACK_LABEL,
        "title": f"Track: {payload['company']} — {payload['launch_name']}"[:240],
        "body": body,
    })
    return f"https://github.com/{repo}/issues/new?{query}"


# ── State ────────────────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "launch"


def _state_path(slug: str) -> str:
    return os.path.join(TRACKING_DIR, slug, "state.json")


def _read_json(path: str):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _parse_issue(issue: dict) -> dict | None:
    m = re.search(r"```json\s*(\{.*?\})\s*```", issue.get("body") or "", re.S)
    if not m:
        print(f"  issue #{issue['number']}: no JSON payload, skipping", file=sys.stderr)
        return None
    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    company = (payload.get("company") or "").strip()
    launch = (payload.get("launch_name") or "").strip()
    if not company:
        return None
    return {
        "slug": _slugify(f"{company}-{launch}"),
        "issue": issue["number"],
        "company": company,
        "launch_name": launch,
        "anchor_date": payload.get("anchor_date") or "",
        "original_score": payload.get("original_score"),
        "url": payload.get("url") or "",
    }


def open_requests() -> list[dict]:
    issues = _api_call(f"/issues?state=open&labels={TRACK_LABEL}&per_page=50") or []
    parsed = [p for p in (_parse_issue(i) for i in issues if "pull_request" not in i) if p]
    parsed.sort(key=lambda p: p["issue"])
    return parsed


def _comment(issue: int, body: str) -> None:
    _api_call(f"/issues/{issue}/comments", "POST", {"body": body})


def _close(issue: int) -> None:
    _api_call(f"/issues/{issue}", "PATCH", {"state": "closed"})


# ── Baseline capture ─────────────────────────────────────────────────────

_BASELINE_QUERIES = [
    "{company} {launch} official announcement",
    "{company} {launch} pricing",
    "{company} {launch} product page features",
]


MIN_BASELINE_CHARS = 500
MAX_BASELINE_PAGES = 6


def _company_tokens(company: str) -> list[str]:
    """Domain-ish tokens for a company name, to spot first-party pages.

    Keeps two-character tokens ("G5") and adds the de-spaced form, since domains
    routinely concatenate ("Ferry Health" -> ferryhealth.com). "ai" is dropped
    because it matches too much as a substring (gmail.com contains it).
    """
    raw = [t for t in re.split(r"[^a-z0-9]+", company.lower()) if t]
    skip = {"the", "inc", "corp", "ai", "and", "group", "technologies"}
    tokens = [t for t in raw if t not in skip and len(t) >= 2]
    joined = "".join(raw)
    if len(joined) >= 4 and joined not in tokens:
        tokens.append(joined)
    return tokens or raw


def _first_party(url: str, tokens: list[str]) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(t in host for t in tokens)


def _capture(tavily: TavilyClient, req: dict) -> dict:
    """Snapshot the artefacts we'll later diff against.

    Ranked so the company's own pages come first: a diff against a third-party
    SEO blog tells us nothing about what the company actually shipped.
    """
    pages: list[dict] = []
    seen: set[str] = set()

    def add(url, title, text):
        # Stubs and link-farm pages produce meaningless diffs.
        if not url or not text or url in seen or len(text.strip()) < MIN_BASELINE_CHARS:
            return
        seen.add(url)
        pages.append({"url": url, "title": title or url, "text": text[:12000]})

    if req.get("url"):
        try:
            for r in tavily.extract(urls=[req["url"]], format="markdown").get("results", []):
                add(r.get("url"), req["launch_name"], r.get("raw_content"))
        except Exception as e:
            print(f"    baseline extract failed: {e}", file=sys.stderr)

    # First-party sweep. The product and pricing pages are the highest-value
    # diff targets ("which 'coming soon' items shipped"), and a generic search
    # often buries them under partner blogs — so search the company's own
    # domain directly, derived from the anchor URL.
    host = urllib.parse.urlparse(req.get("url") or "").netloc.lower()
    host = re.sub(r"^www\.", "", host)
    if host:
        for query in (req["launch_name"], f"{req['launch_name']} pricing"):
            try:
                for r in tavily.search(
                    query=query, search_depth="advanced", max_results=4,
                    include_domains=[host], include_raw_content="markdown",
                ).get("results", []):
                    add(r.get("url"), r.get("title"),
                        r.get("raw_content") or r.get("content"))
            except Exception as e:
                print(f"    first-party search failed ({query!r}): {e}", file=sys.stderr)

    for template in _BASELINE_QUERIES:
        query = template.format(company=req["company"], launch=req["launch_name"])
        try:
            for r in tavily.search(
                query=query, search_depth="advanced", max_results=3,
                include_raw_content="markdown",
            ).get("results", []):
                add(r.get("url"), r.get("title"), r.get("raw_content") or r.get("content"))
        except Exception as e:
            print(f"    baseline search failed ({query!r}): {e}", file=sys.stderr)

    tokens = _company_tokens(req.get("company", ""))
    pages.sort(key=lambda p: (not _first_party(p["url"], tokens), -len(p["text"])))
    kept = pages[:MAX_BASELINE_PAGES]
    first_party = sum(1 for p in kept if _first_party(p["url"], tokens))
    print(f"    kept {len(kept)}/{len(pages)} page(s), {first_party} first-party")

    return {"captured": date.today().isoformat(), "pages": kept}


# ── Checkpoint research ──────────────────────────────────────────────────

_CHECKPOINT_QUERIES = [
    "{company} {launch} announcement news",
    "{company} {launch} customers using case study",
    "{company} {launch} partners integration",
    "{company} {launch} webinar event session",
    "{company} {launch} analyst Gartner Forrester review",
    "{company} {launch} general availability now available",
    "{company} {launch} review G2 TrustRadius",
    "{company} {launch} keynote conference recap",
    "{company} careers hiring {launch}",
]


def _research(tavily: TavilyClient, state: dict, since: str) -> tuple[list[dict], list[dict]]:
    """New signals since `since`, plus a re-fetch of the baseline pages to diff."""
    company, launch = state["company"], state["launch_name"]
    signals: list[dict] = []
    seen: set[str] = set()

    for template in _CHECKPOINT_QUERIES:
        query = template.format(company=company, launch=launch)
        try:
            results = tavily.search(
                query=query, search_depth="advanced", max_results=5,
                start_date=since, include_raw_content="markdown",
            ).get("results", [])
        except Exception as e:
            print(f"    search failed ({query!r}): {e}", file=sys.stderr)
            continue
        for r in results:
            url = r.get("url")
            if url and url not in seen:
                seen.add(url)
                signals.append({
                    "url": url,
                    "title": r.get("title") or url,
                    "date": r.get("published_date") or "",
                    "text": (r.get("raw_content") or r.get("content") or "")[:4000],
                })

    baseline = _read_json(os.path.join(TRACKING_DIR, state["slug"], "baseline.json")) or {}
    current: list[dict] = []
    for page in baseline.get("pages", [])[:4]:
        try:
            for r in tavily.extract(urls=[page["url"]], format="markdown").get("results", []):
                current.append({
                    "url": page["url"],
                    "title": page["title"],
                    "baseline_text": page["text"][:6000],
                    "current_text": (r.get("raw_content") or "")[:6000],
                })
        except Exception as e:
            print(f"    re-extract failed for {page['url']}: {e}", file=sys.stderr)

    return signals, current


_CHECKPOINT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "momentum", "headline", "shipped_vs_promised", "channel_activity",
        "third_party_validation", "messaging_evolution", "hiring_signal",
        "steal_this", "sustained_score", "score_rationale", "sources",
    ],
    "properties": {
        "momentum": {
            "type": "string",
            "enum": ["accelerating", "sustained", "decaying", "abandoned", "unclear"],
        },
        "headline": {
            "type": "string",
            "description": (
                "The single most important development since the last checkpoint, in "
                "one sentence. This is what goes in the email summary, so make it "
                "carry real information rather than a generic status line."
            ),
        },
        "shipped_vs_promised": {
            "type": "string",
            "description": (
                "What was promised at launch versus what has actually shipped. Use "
                "the baseline-vs-current page comparison: 'coming soon' items that "
                "went GA, pricing changes, new modules, quiet removals."
            ),
        },
        "channel_activity": {
            "type": "string",
            "description": (
                "GTM motion since the last checkpoint: conference sessions and "
                "recorded content, webinars, partner and customer announcements, "
                "content cadence, paid or field motion. Be specific and name things."
            ),
        },
        "third_party_validation": {"type": "string"},
        "messaging_evolution": {
            "type": "string",
            "description": (
                "How the narrative changed: new proof points, claims quietly "
                "dropped, repositioning, vocabulary shifts."
            ),
        },
        "hiring_signal": {"type": "string"},
        "steal_this": {
            "type": "string",
            "description": (
                "One portable lesson about SUSTAINED go-to-market — distinct from a "
                "launch-moment tactic. What did they do after week one that a reader "
                "should copy, or fail to do that they should avoid?"
            ),
        },
        "sustained_score": {
            "type": ["number", "null"],
            "description": (
                "1-10 for campaign execution since launch, at the 12-week checkpoint "
                "only. Null at 4 and 8 weeks — too early to judge. This is separate "
                "from the original launch-moment score, which stays untouched."
            ),
        },
        "score_rationale": {"type": "string"},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "url"],
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                },
            },
        },
    },
}


def _analyze(
    claude: anthropic.Anthropic,
    state: dict,
    week: int,
    signals: list[dict],
    diffs: list[dict],
    prior: list[dict],
) -> dict:
    signal_block = "\n\n".join(
        f"=== {s['title']} ({s['date'] or 'no date'})\nURL: {s['url']}\n\n{s['text']}"
        for s in signals
    ) or "(No new signals retrieved.)"

    diff_block = "\n\n".join(
        f"=== PAGE: {d['title']}\nURL: {d['url']}\n"
        f"--- AT TRACKING START ---\n{d['baseline_text']}\n"
        f"--- NOW ---\n{d['current_text']}"
        for d in diffs
    ) or "(No baseline pages available to compare.)"

    prior_block = "\n\n".join(
        f"Week {p['week']} ({p['date']}) — momentum: {p['data'].get('momentum')}\n"
        f"{p['data'].get('headline', '')}\n{p['data'].get('shipped_vs_promised', '')}"
        for p in prior
    ) or "(This is the first checkpoint.)"

    score_instruction = (
        "This is the 12-week checkpoint, so assign `sustained_score` (1-10) for "
        f"campaign execution since launch. The original launch-moment score was "
        f"{state.get('original_score')}. Do not revise that score — it stands as the "
        "record of what the launch looked like on day one. The interesting signal is "
        "the GAP between the two, so explain it in `score_rationale`."
        if week == 12 else
        f"This is the {week}-week checkpoint. Set `sustained_score` to null — it is "
        "too early to score a campaign. Explain in `score_rationale` what you would "
        "need to see by week 12 to call this strong."
    )

    prompt = f"""You are an expert B2B product marketing strategist. Your reader is a VP of Product Marketing who wants to learn how great launches are sustained, not just how they are announced.

You are writing the {week}-WEEK follow-up on a launch first profiled on {state['anchor_date']}.

LAUNCH: {state['company']} — {state['launch_name']}
Original launch-moment score: {state.get('original_score')}

WHY THIS EXISTS: the weekly digest only ever sees the launch moment, which biases it toward whatever assets happened to exist on announcement day. The most important launches get sustained GTM investment for months afterward. Your job is to find out what actually happened next.

PRIOR CHECKPOINTS:
{prior_block}

{score_instruction}

HOW TO READ THE EVIDENCE:
- The page comparison below is the highest-value input. It shows the same pages as captured when tracking began and as they are now. Use it to establish what actually shipped versus what was merely promised — "coming soon" items going GA, pricing appearing or changing, modules added or quietly removed, hero messaging rewritten.
- The signals are search results from after the anchor date. Weigh company-owned sources for intent and third-party sources for traction.
- Do not treat absence of evidence as evidence of absence. If you cannot find webinars, say you could not find them — do not assert there were none. Retrieval is imperfect and a confident negative is worse than an honest gap.
- Distinguish genuine momentum from noise. A reposted press release is not momentum. A named customer telling their own story, a conference session with recorded content, a partner building on the product, an analyst note, a pricing page that now lists what was previously "contact us" — those are momentum.

Write in plain, direct language. No filler that editorially validates the company. If the campaign went quiet, say so plainly — a launch that faded after a strong announcement is one of the most instructive cases this reader can study.

PAGE COMPARISON (tracking start vs now):
{diff_block}

SIGNALS SINCE {state['anchor_date']}:
{signal_block}
"""

    return structured(
        claude,
        prompt,
        _CHECKPOINT_SCHEMA,
        effort="high",
        label=f"{state['company']} week {week}",
    )


# ── Orchestration ────────────────────────────────────────────────────────


def _due_checkpoint(state: dict, today: date) -> int | None:
    """The earliest checkpoint that is due and not yet done (one per week)."""
    try:
        anchor = datetime.strptime(state["anchor_date"], "%Y-%m-%d").date()
    except (ValueError, KeyError):
        return None
    elapsed = (today - anchor).days
    done = set(state.get("checkpoints_done", []))
    for week in CHECKPOINT_WEEKS:
        if week not in done and elapsed >= week * 7:
            return week
    return None


def _adopt(tavily: TavilyClient, req: dict, today: date) -> dict:
    """First time we see a tracking request: capture the baseline."""
    print(f"  adopting #{req['issue']}: {req['company']} — {req['launch_name']}")
    baseline = _capture(tavily, req)
    _write_json(os.path.join(TRACKING_DIR, req["slug"], "baseline.json"), baseline)

    state = dict(req)
    state["baseline_captured"] = baseline["captured"]
    state["checkpoints_done"] = []
    _write_json(_state_path(req["slug"]), state)

    anchor = state.get("anchor_date") or today.isoformat()
    try:
        anchor_d = datetime.strptime(anchor, "%Y-%m-%d").date()
        schedule = "\n".join(
            f"- {w}-week: {(anchor_d + timedelta(weeks=w)).isoformat()}"
            for w in CHECKPOINT_WEEKS
        )
    except ValueError:
        schedule = "(could not parse the anchor date)"

    _comment(
        req["issue"],
        f"**Tracking started.** Captured {len(baseline['pages'])} baseline page(s) "
        f"to diff against later.\n\nAnchor date (first appeared in the digest): "
        f"`{anchor}`\n\nCheckpoints due:\n{schedule}\n\nEach checkpoint will be "
        f"posted here and summarised in that week's digest email.",
    )
    return state


def run_checkpoints(
    tavily: TavilyClient,
    claude: anthropic.Anthropic,
    today: date | None = None,
) -> list[dict]:
    """Adopt new requests, run any due checkpoints, return updates for this week."""
    today = today or date.today()

    requests = open_requests()
    if not requests:
        return []

    active, queued = requests[:MAX_ACTIVE], requests[MAX_ACTIVE:]
    for req in queued:
        print(f"  queued (cap {MAX_ACTIVE}): {req['company']} — {req['launch_name']}")

    updates = []
    for req in active:
        state = _read_json(_state_path(req["slug"]))
        if not state:
            state = _adopt(tavily, req, today)

        week = _due_checkpoint(state, today)
        if week is None:
            print(f"  nothing due: {state['company']}")
            continue

        late = (today - datetime.strptime(state["anchor_date"], "%Y-%m-%d").date()).days - week * 7
        print(f"  week {week} checkpoint: {state['company']}" + (f" (+{late}d late)" if late > 7 else ""))

        done = state.get("checkpoints_done", [])
        since = state["anchor_date"]
        prior = []
        for w in CHECKPOINT_WEEKS:
            if w in done:
                data = _read_json(os.path.join(TRACKING_DIR, state["slug"], f"checkpoint-{w}.json"))
                if data:
                    prior.append({"week": w, "date": data.get("run_date", ""), "data": data})
                    since = data.get("run_date") or since

        signals, diffs = _research(tavily, state, since)
        print(f"    {len(signals)} signal(s), {len(diffs)} page comparison(s)")

        try:
            result = _analyze(claude, state, week, signals, diffs, prior)
        except Exception as e:
            print(f"    checkpoint failed: {e}", file=sys.stderr)
            continue

        result["run_date"] = today.isoformat()
        result["week"] = week
        _write_json(
            os.path.join(TRACKING_DIR, state["slug"], f"checkpoint-{week}.json"), result
        )

        state["checkpoints_done"] = sorted(done + [week])
        _write_json(_state_path(state["slug"]), state)

        _comment(state["issue"], _issue_comment(state, result))
        if week == CHECKPOINT_WEEKS[-1]:
            _comment(
                state["issue"],
                "12-week tracking complete — closing. Reopen or re-track if you want "
                "to keep following this one.",
            )
            _close(state["issue"])

        updates.append({
            "slug": state["slug"],
            "company": state["company"],
            "launch_name": state["launch_name"],
            "anchor_date": state["anchor_date"],
            "original_score": state.get("original_score"),
            "week": week,
            **result,
        })

    return updates


_FIELDS = [
    ("shipped_vs_promised", "Shipped vs promised"),
    ("channel_activity", "Channel activity"),
    ("third_party_validation", "Third-party validation"),
    ("messaging_evolution", "Messaging evolution"),
    ("hiring_signal", "Hiring signal"),
]


def track_urls_from_history(weeks: int = 8) -> list[tuple[str, str, str]]:
    """(label, anchor_date, url) for launches already published.

    The button only exists in emails sent from now on, so this is how you start
    tracking something from a past edition.
    """
    from . import history as hist

    rows = []
    for week in hist.load_history().get("weeks", [])[-weeks:]:
        for item in week.get("launches", []):
            entry = {
                "company": item.get("company", ""),
                "launch_name": item.get("launch_name", ""),
                "score": item.get("score"),
                "sources": [{"url": item.get("url", "")}] if item.get("url") else [],
            }
            url = track_button_url(entry, week["date"])
            if url:
                label = f"{item.get('company')} — {item.get('launch_name')}"
                rows.append((label, week["date"], url))
    return rows


def _issue_comment(state: dict, result: dict) -> str:
    lines = [
        f"## Week {result['week']} checkpoint — {result['run_date']}",
        "",
        f"**Momentum:** {result.get('momentum', '?')}",
        "",
        f"**{result.get('headline', '')}**",
        "",
    ]
    for key, label in _FIELDS:
        if result.get(key):
            lines += [f"**{label}**", result[key], ""]
    if result.get("steal_this"):
        lines += ["**Steal this (sustained GTM)**", result["steal_this"], ""]
    if result.get("sustained_score") is not None:
        lines += [
            f"**Sustained-GTM score: {result['sustained_score']:g}/10** "
            f"(launch-moment score was {state.get('original_score')})",
            result.get("score_rationale", ""),
            "",
        ]
    elif result.get("score_rationale"):
        lines += ["**What would make this strong by week 12**", result["score_rationale"], ""]
    if result.get("sources"):
        lines.append("**Sources**")
        lines += [f"- [{s['title']}]({s['url']})" for s in result["sources"][:8]]
    return "\n".join(lines)


def _cli() -> None:
    """List published launches with a ready-made tracking link for each."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python3 -m digest.tracking",
        description="Start tracking a launch from a past digest edition.",
    )
    parser.add_argument(
        "--weeks", type=int, default=8, help="How many past editions to list."
    )
    parser.add_argument("--match", help="Only show launches matching this text.")
    args = parser.parse_args()

    rows = track_urls_from_history(args.weeks)
    if args.match:
        needle = args.match.lower()
        rows = [r for r in rows if needle in r[0].lower()]

    if not rows:
        print("No matching launches found in the digest history.")
        return

    print(f"{len(rows)} launch(es). Open a link and press 'Submit new issue':\n")
    for label, anchor, url in rows:
        print(f"  {anchor}  {label}")
        print(f"    {url}\n")


if __name__ == "__main__":
    _cli()
