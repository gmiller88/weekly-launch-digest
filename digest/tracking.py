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

# What we keep from a page. Storing a typed snapshot rather than raw page text
# keeps third-party prose out of this public repo, and makes the later
# comparison sharper: we diff the fields that carry meaning ("coming soon" ->
# "available now", a price appearing) instead of reflowed paragraphs.
_SNAPSHOT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "hero_headline", "hero_subhead", "positioning_claims", "modules",
        "available_now", "coming_soon", "pricing", "named_customers",
        "events_mentioned", "primary_cta", "notes",
    ],
    "properties": {
        "hero_headline": {"type": "string"},
        "hero_subhead": {"type": "string"},
        "positioning_claims": {
            "type": "array", "items": {"type": "string"},
            "description": "Headline claims and proof points, each one short.",
        },
        "modules": {
            "type": "array", "items": {"type": "string"},
            "description": "Named products, features, skills, SKUs or tiers.",
        },
        "available_now": {
            "type": "array", "items": {"type": "string"},
            "description": "Items presented as shipped, GA or generally available.",
        },
        "coming_soon": {
            "type": "array", "items": {"type": "string"},
            "description": (
                "Items marked coming soon, preview, beta, waitlist, or promised "
                "for a future date. This is the highest-value field: the later "
                "comparison turns it into what actually shipped."
            ),
        },
        "pricing": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item", "price"],
                "properties": {
                    "item": {"type": "string"},
                    "price": {
                        "type": "string",
                        "description": "Verbatim, including 'contact us' or 'free'.",
                    },
                },
            },
        },
        "named_customers": {"type": "array", "items": {"type": "string"}},
        "events_mentioned": {"type": "array", "items": {"type": "string"}},
        "primary_cta": {"type": "string"},
        "notes": {
            "type": "string",
            "description": "Anything else materially useful for a later comparison.",
        },
    },
}


def _snapshot(
    tavily: TavilyClient,
    claude: anthropic.Anthropic,
    urls: list[str],
    label: str,
) -> dict:
    """Fetch these pages and reduce them to a typed snapshot."""
    texts = []
    for url in urls:
        try:
            for r in tavily.extract(urls=[url], format="markdown").get("results", []):
                raw = (r.get("raw_content") or "").strip()
                if len(raw) >= MIN_BASELINE_CHARS:
                    texts.append(f"=== {url}\n\n{raw[:12000]}")
        except Exception as e:
            print(f"    extract failed for {url}: {e}", file=sys.stderr)

    if not texts:
        return {}

    prompt = f"""Extract a structured snapshot of this product's public positioning, exactly as these pages present it today.

This snapshot will be compared against another one captured weeks later, to establish what the company actually shipped versus what it merely promised. So be precise and literal:

- Record what the pages SAY, not what you know from elsewhere.
- Quote names and prices verbatim. If pricing says "contact us", record that.
- `coming_soon` is the most important field. Capture anything framed as coming soon, in preview, in beta, waitlisted, or promised for a named future quarter or date — with enough detail to recognise the same item later.
- `available_now` should only hold things the pages present as actually shipped.
- Keep list entries short and comparable. Prefer "Financial Services Cloud skills" over a full sentence.
- If a field genuinely has nothing, return an empty list or empty string rather than inventing content.

PAGES ({label}):

{chr(10).join(texts)}
"""
    try:
        return structured(
            claude, prompt, _SNAPSHOT_SCHEMA,
            effort="medium", max_tokens=8000, label=f"snapshot {label}",
        )
    except Exception as e:
        print(f"    snapshot failed: {e}", file=sys.stderr)
        return {}


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


def _capture(tavily: TavilyClient, claude: anthropic.Anthropic, req: dict) -> dict:
    """Snapshot the artefacts we'll later compare against.

    Ranked so the company's own pages come first: a comparison against a
    third-party SEO blog tells us nothing about what the company actually
    shipped.
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

    urls = [p["url"] for p in kept]
    snapshot = _snapshot(
        tavily, claude, urls, f"{req['company']} {req['launch_name']} at tracking start"
    )
    if snapshot:
        print(
            f"    snapshot: {len(snapshot.get('coming_soon', []))} coming-soon, "
            f"{len(snapshot.get('available_now', []))} available, "
            f"{len(snapshot.get('pricing', []))} price point(s)"
        )

    # Only the snapshot and the URLs are kept — no raw third-party page text.
    return {"captured": date.today().isoformat(), "urls": urls, "snapshot": snapshot}


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


def _research(
    tavily: TavilyClient,
    claude: anthropic.Anthropic,
    state: dict,
    since: str,
) -> tuple[list[dict], dict, dict]:
    """New signals since `since`, plus baseline and current snapshots to compare."""
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
    urls = baseline.get("urls") or []
    current = (
        _snapshot(tavily, claude, urls, f"{state['company']} {state['launch_name']} now")
        if urls else {}
    )

    return signals, baseline.get("snapshot") or {}, current


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
    baseline_snapshot: dict,
    current_snapshot: dict,
    prior: list[dict],
) -> dict:
    signal_block = "\n\n".join(
        f"=== {s['title']} ({s['date'] or 'no date'})\nURL: {s['url']}\n\n{s['text']}"
        for s in signals
    ) or "(No new signals retrieved.)"

    captured = state.get("baseline_captured", "")
    if baseline_snapshot and current_snapshot:
        diff_block = (
            f"AT TRACKING START (captured {captured or 'unknown date'}):\n"
            + json.dumps(baseline_snapshot, indent=2, ensure_ascii=False)
            + "\n\nNOW:\n"
            + json.dumps(current_snapshot, indent=2, ensure_ascii=False)
        )
    else:
        diff_block = "(No usable snapshot comparison available.)"

    # Retroactively-tracked launches get their baseline long after announcement,
    # so the comparison window can be much shorter than the checkpoint age.
    window_note = ""
    try:
        anchor_d = datetime.strptime(state["anchor_date"], "%Y-%m-%d").date()
        captured_d = datetime.strptime(captured, "%Y-%m-%d").date()
        lag = (captured_d - anchor_d).days
        if lag > 7:
            window_note = (
                f"\nIMPORTANT — the baseline was captured {lag} days AFTER this launch "
                f"was first profiled, because tracking started retroactively. So the "
                f"snapshot comparison only covers from {captured} onward, not from the "
                f"launch. Anything that shipped between {state['anchor_date']} and "
                f"{captured} will already appear in the 'AT TRACKING START' side and "
                f"will NOT show up as a change. Lean on the signals for that earlier "
                f"period, and do not read an unchanged snapshot as evidence of a "
                f"stalled campaign.\n"
            )
    except (ValueError, KeyError):
        pass

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
- The snapshot comparison below is the highest-value input. Both objects were extracted from the same company-owned pages using the same schema — one when tracking began, one now. Compare them field by field. An item moving from `coming_soon` to `available_now` is a shipped promise. An item still in `coming_soon` after {week} weeks is a slipped one. Something that vanished from both was dropped quietly. Watch `pricing` for figures replacing "contact us", `modules` for additions and removals, and `hero_headline` / `positioning_claims` for repositioning.
- Snapshot extraction is imperfect. If a field is empty in one snapshot but populated in the other, consider that it may be an extraction miss rather than a real change, and say so rather than over-reading it.
- The signals are search results from after the anchor date. Weigh company-owned sources for intent and third-party sources for traction.
- Do not treat absence of evidence as evidence of absence. If you cannot find webinars, say you could not find them — do not assert there were none. Retrieval is imperfect and a confident negative is worse than an honest gap.
- Distinguish genuine momentum from noise. A reposted press release is not momentum. A named customer telling their own story, a conference session with recorded content, a partner building on the product, an analyst note, a pricing page that now lists what was previously "contact us" — those are momentum.

Write in plain, direct language. No filler that editorially validates the company. If the campaign went quiet, say so plainly — a launch that faded after a strong announcement is one of the most instructive cases this reader can study.

SNAPSHOT COMPARISON (same pages, same schema, tracking start vs now):
{window_note}{diff_block}

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


def _adopt(
    tavily: TavilyClient,
    claude: anthropic.Anthropic,
    req: dict,
    today: date,
) -> dict:
    """First time we see a tracking request: capture the baseline."""
    print(f"  adopting #{req['issue']}: {req['company']} — {req['launch_name']}")
    baseline = _capture(tavily, claude, req)
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
        f"**Tracking started.** Snapshotted {len(baseline.get('urls', []))} "
        f"company page(s) to compare against later.\n\n"
        f"Anchor date (first appeared in the digest): "
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
            state = _adopt(tavily, claude, req, today)

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

        signals, base_snap, cur_snap = _research(tavily, claude, state, since)
        print(
            f"    {len(signals)} signal(s), snapshot comparison: "
            f"{'yes' if base_snap and cur_snap else 'unavailable'}"
        )

        try:
            result = _analyze(
                claude, state, week, signals, base_snap, cur_snap, prior
            )
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
