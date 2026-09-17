"""B2B product launch digest.

Two passes. Pass one sweeps the week's news and shortlists candidates. Pass two
researches each shortlisted launch against its primary sources — the company's
own announcement, landing page, pricing page — and only then analyses it.

The old single-pass design graded a 700-character news snippet, which meant it
kept docking launches for campaign work it simply couldn't see.
"""

import sys

import anthropic
from tavily import TavilyClient

from . import history as hist
from .llm import StructureError, require_complete, structured

MAX_ENTRIES = 5

# Outlets whose coverage actually signals a launch mattered.
_TIER1 = [
    "techcrunch.com",
    "theverge.com",
    "wsj.com",
    "bloomberg.com",
    "reuters.com",
    "forbes.com",
    "businessinsider.com",
    "axios.com",
    "theinformation.com",
    "venturebeat.com",
    "cnbc.com",
    "fortune.com",
    "siliconangle.com",
]

# Where launches surface before the press notices.
_COMMUNITY = ["producthunt.com", "news.ycombinator.com", "linkedin.com"]

_BROAD_QUERIES = [
    "B2B software product launch announcement this week",
    "SaaS startup new product launch this week",
    "enterprise software launch keynote announcement this week",
    "B2B platform new product general availability announcement",
    "startup launches out of stealth enterprise software",
]

_TIER1_QUERIES = [
    "B2B software launch",
    "enterprise AI product launch",
    "SaaS platform launch announcement",
]

_COMMUNITY_QUERIES = [
    "B2B SaaS launch developer tool",
    "enterprise software launch trending",
]

# Fixed anchors so a 6 means the same thing in November as it did in June.
# Described at the level of execution shape, not specific claims.
_RATING_ANCHORS = """\
SCORE ANCHORS — calibrate against these fixed reference points every week:

- 10 — The category-defining launch. A new product whose name becomes the name of
  its category. Saturation coverage the company didn't have to buy, a narrative
  competitors are forced to respond to, and a product-led loop where usage itself
  drives acquisition. Think: the launch that textbooks get written about.
- 9 — Exceptional narrative plus a distribution mechanic doing real work: engineered
  scarcity (invite-only, waitlist with status), a co-announcement roster where every
  name is a specific credibility signal, or a free tier designed as a wedge.
  Tier-1 press plus genuine community pull.
- 7 — Strong, professional launch with one standout element. A real conference
  keynote slot, or sharp category-creation messaging, or an excellent demo asset.
  Coverage is earned, not just distributed. Nothing embarrassing, nothing viral.
- 5 — Competent and forgettable. Wire distribution, some trade pickup, accurate but
  generic messaging ("next-generation", "AI-powered"), no proof points, no hook.
  The launch happened. Nobody's behaviour changed.
- 3 — A changelog entry with a press release stapled to it. No narrative, no
  audience definition, no activation path. Often a real product improvement that
  was given no chance to land.

Use the full range. If a launch is genuinely a 9, say 9. If it's a 3, say 3.
Do not cluster everything between 4 and 7 — a compressed scale teaches nothing.
"""

_SHORTLIST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidates", "corpus_assessment"],
    "properties": {
        "corpus_assessment": {
            "type": "string",
            "description": (
                "One or two sentences on the quality of the SOURCE CORPUS you were "
                "given — not the state of the B2B market. Say plainly whether the "
                "retrieval surfaced real launch coverage or mostly wire copy and "
                "roundups."
            ),
        },
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "company",
                    "launch_name",
                    "url",
                    "why_shortlisted",
                    "research_query",
                ],
                "properties": {
                    "company": {"type": "string"},
                    "launch_name": {"type": "string"},
                    "url": {"type": "string"},
                    "why_shortlisted": {"type": "string"},
                    "research_query": {
                        "type": "string",
                        "description": (
                            "A web search query that will find this launch's PRIMARY "
                            "sources — the company's own announcement post, landing "
                            "page, or press release. Name the company and product "
                            "explicitly."
                        ),
                    },
                },
            },
        },
    },
}

_ENTRY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "company",
        "launch_name",
        "assessable",
        "score",
        "company_blurb",
        "the_launch",
        "product_fit",
        "launch_playbook",
        "messaging",
        "why_this_rating",
        "steal_this",
        "evidence_note",
        "sources",
    ],
    "properties": {
        "company": {"type": "string"},
        "launch_name": {"type": "string"},
        "assessable": {
            "type": "boolean",
            "description": (
                "False when the available evidence genuinely doesn't support a launch "
                "execution judgement. Prefer this over inventing a mediocre score."
            ),
        },
        "score": {
            "type": ["number", "null"],
            "description": "1-10 against the anchors. Null when assessable is false.",
        },
        "company_blurb": {"type": "string"},
        "the_launch": {"type": "string"},
        "product_fit": {"type": "string"},
        "launch_playbook": {"type": "string"},
        "messaging": {"type": "string"},
        "why_this_rating": {"type": "string"},
        "steal_this": {
            "type": "string",
            "description": (
                "One specific, portable tactic the reader could apply to their own "
                "next B2B launch. Concrete and transferable — a mechanic, a sequencing "
                "choice, a framing device. Not 'have good messaging'."
            ),
        },
        "evidence_note": {
            "type": "string",
            "description": (
                "What you actually read, and what you could not verify. Name the "
                "primary sources if you had them. Never present an absence of "
                "evidence as evidence of absence."
            ),
        },
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

_SYNTHESIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["analyst_note", "pattern_watch"],
    "properties": {
        "analyst_note": {
            "type": "string",
            "description": (
                "2-3 sentences framing THIS WEEK's launches. Comment on the launches "
                "themselves. Do not describe the retrieval corpus, and do not open "
                "with 'this was a thin week' — that has been overused."
            ),
        },
        "pattern_watch": {
            "type": "string",
            "description": (
                "2-4 sentences on what's visible ACROSS the recent weeks of coverage "
                "supplied: a recurring tactic, a shift in how companies are framing "
                "launches, a playbook showing up repeatedly. Reference specific prior "
                "weeks. This is the compounding value of reading every week."
            ),
        },
    },
}


def _search(tavily: TavilyClient, **kwargs) -> list[dict]:
    try:
        return tavily.search(**kwargs).get("results", [])
    except Exception as e:  # one bad sweep shouldn't kill the run
        print(f"  search failed ({kwargs.get('query')!r}): {e}", file=sys.stderr)
        return []


def _gather_candidates(tavily: TavilyClient) -> list[dict]:
    """Sweep the week from three angles: broad news, tier-1 outlets, community."""
    seen: set[str] = set()
    articles: list[dict] = []

    def add(results):
        for r in results:
            url = r.get("url")
            if url and url not in seen:
                seen.add(url)
                articles.append(r)

    for query in _BROAD_QUERIES:
        add(_search(tavily, query=query, search_depth="advanced", topic="news",
                    days=7, max_results=8))

    for query in _TIER1_QUERIES:
        add(_search(tavily, query=query, search_depth="advanced", topic="news",
                    days=7, max_results=8, include_domains=_TIER1))

    for query in _COMMUNITY_QUERIES:
        add(_search(tavily, query=query, search_depth="advanced",
                    days=7, max_results=6, include_domains=_COMMUNITY))

    return articles


def _shortlist(
    claude: anthropic.Anthropic,
    articles: list[dict],
    history: dict,
) -> dict:
    corpus = "\n\n---\n\n".join(
        f"TITLE: {a.get('title', '')}\nURL: {a.get('url', '')}\n"
        f"SUMMARY: {(a.get('content') or '')[:700]}"
        for a in articles
    )

    exclusions = hist.launch_exclusions(history)
    exclusion_block = (
        "\n".join(f"- {k}" for k in exclusions) if exclusions else "(nothing yet)"
    )

    prompt = f"""You are an expert B2B product marketing strategist. Your reader is a VP of Product Marketing who wants to (a) know about high-quality B2B product launches and (b) learn the craft of how companies bring products to market.

This is PASS ONE of two. Your only job here is to shortlist candidates worth deep research. Do not analyse them yet.

Select up to {MAX_ENTRIES} of the most promising B2B software product launches from the corpus below.

WHAT QUALIFIES:
- Net-new products or product lines
- Major features launched with a dedicated campaign (not a changelog entry)
- Platform expansions that open a new market or category
- Companies emerging from stealth with a product

WHAT DOES NOT QUALIFY — be strict, these have polluted past editions:
- Funding announcements with no product launch attached
- Awards, "top rated" lists, partnership news with no product
- Consumer product launches (judge by who signs the cheque, not the brand)
- Acquisitions, earnings, personnel news
- Weekly tool roundups on SMB blogs, unless the underlying launch is genuinely notable

COMPANY SCOPE: Prioritise startups and growth-stage companies — the majority of the list. Enterprise incumbents (Salesforce, Microsoft, Google, Oracle, SAP, Adobe) face a higher bar: the launch must be genuinely category-defining or a strategic pivot that reshapes competitive dynamics. A solid enterprise feature release is not enough.

ALREADY COVERED — do not shortlist these again unless there is a genuinely NEW launch from that company:
{exclusion_block}

QUALITY OVER QUANTITY: {MAX_ENTRIES} is a ceiling, not a quota. If only two launches genuinely qualify, return two. Padding the list with weak entries is worse than a short list — it has actively degraded past editions.

For each candidate, write a `research_query` that will find the company's OWN announcement — their blog post, newsroom entry, or landing page. This drives pass two, so make it specific and name the company and product.

Also assess the CORPUS itself, honestly. If the retrieval mostly returned wire copy and roundups rather than real launch coverage, say so plainly — that is a signal about the pipeline, and it is useful.

CORPUS ({len(articles)} articles from the past 7 days):
{corpus}
"""

    return structured(
        claude,
        prompt,
        _SHORTLIST_SCHEMA,
        effort="high",
        label="shortlist",
    )


def _research(tavily: TavilyClient, candidate: dict) -> list[dict]:
    """Pull the primary artefacts for one launch: the company's own words."""
    company = candidate.get("company", "")
    sources: list[dict] = []
    seen: set[str] = set()

    def add(url, title, text):
        if not url or url in seen or not text:
            return
        seen.add(url)
        sources.append({"url": url, "title": title or url, "text": text[:7000]})

    # The article that surfaced it, in full rather than as a snippet.
    url = candidate.get("url")
    if url:
        try:
            extracted = tavily.extract(urls=[url], format="markdown")
            for r in extracted.get("results", []):
                add(r.get("url"), candidate.get("launch_name"), r.get("raw_content"))
        except Exception as e:
            print(f"  extract failed for {url}: {e}", file=sys.stderr)

    # The company's own announcement, landing page, pricing page.
    for result in _search(
        tavily,
        query=candidate.get("research_query") or f"{company} launch announcement",
        search_depth="advanced",
        max_results=4,
        include_raw_content="markdown",
    ):
        add(
            result.get("url"),
            result.get("title"),
            result.get("raw_content") or result.get("content"),
        )

    return sources


def _analyze(
    claude: anthropic.Anthropic,
    candidate: dict,
    sources: list[dict],
) -> dict:
    if sources:
        source_block = "\n\n".join(
            f"=== SOURCE: {s['title']}\nURL: {s['url']}\n\n{s['text']}"
            for s in sources
        )
        evidence_framing = (
            f"You have {len(sources)} source document(s) below, including page text "
            f"rather than just snippets. Read them properly before judging."
        )
    else:
        source_block = "(No sources could be retrieved.)"
        evidence_framing = (
            "Primary source retrieval FAILED for this launch. You are working from "
            "the shortlist note alone. Set assessable to false unless you have "
            "genuine independent knowledge of this launch."
        )

    prompt = f"""You are an expert B2B product marketing strategist writing for a VP of Product Marketing. They want to know which B2B launches were genuinely good, and to learn the craft from how those launches were executed.

This is PASS TWO. Analyse this one launch in depth.

LAUNCH: {candidate.get('company')} — {candidate.get('launch_name')}
WHY IT WAS SHORTLISTED: {candidate.get('why_shortlisted')}

{evidence_framing}

{_RATING_ANCHORS}

CRITICAL RULE ON EVIDENCE — this is the single biggest failure mode of earlier editions:
Do not treat absence of evidence as evidence of absence. Earlier editions repeatedly wrote "no evidence of a conference slot" or "no demo video is evident" when the real situation was that the source snippet simply didn't mention one. That produced scores that measured retrieval quality rather than launch quality, and it was misleading.

So:
- Judge what you can actually see in the sources.
- When you cannot verify a channel or tactic, say so in `evidence_note` — not in `why_this_rating`, and never as a deduction.
- Only deduct for something you can affirmatively observe (muddled messaging you read, a missing narrative in a post you have, a pricing page that undercuts the pitch).
- If the evidence is too thin to judge execution at all, set `assessable` to false and `score` to null. An honest "not assessable" is far more useful than a fabricated 5.

On `launch_playbook` and `messaging`: these are the two fields the reader learns most from. Be specific and concrete. Quote or paraphrase actual phrasing where you have it. Name the mechanics you can see — the sequencing, the asset mix, the proof points, what the landing page leads with, what the pricing page reveals, who they co-announced with and why that name specifically.

On `steal_this`: give one portable tactic the reader could actually apply. Specific and transferable. Not "invest in good messaging".

Write in plain, direct language. No filler that editorially validates the launch ("signalling strong momentum", "underscoring their commitment"). Describe and assess; don't cheerlead.

SOURCES:
{source_block}
"""

    def validate(data: dict) -> None:
        require_complete(
            "company_blurb",
            "the_launch",
            "product_fit",
            "launch_playbook",
            "messaging",
            "steal_this",
        )({"entries": [data]})
        if data.get("assessable") and data.get("score") is None:
            raise StructureError("assessable entry has no score")

    return structured(
        claude,
        prompt,
        _ENTRY_SCHEMA,
        validate=validate,
        effort="high",
        label=f"analyze {candidate.get('company')}",
    )


def _synthesize(
    claude: anthropic.Anthropic,
    entries: list[dict],
    history: dict,
    corpus_assessment: str,
) -> dict:
    this_week = "\n".join(
        f"- [{e.get('score') if e.get('score') is not None else 'n/a'}/10] "
        f"{e.get('company')} — {e.get('launch_name')}: {e.get('launch_playbook', '')[:300]}"
        for e in entries
    )

    prompt = f"""You are an expert B2B product marketing strategist writing the framing for this week's launch digest. Your reader is a VP of Product Marketing building an eye for best-in-class launches.

THIS WEEK'S ANALYSED LAUNCHES:
{this_week or "(none qualified this week)"}

PRIOR WEEKS ALREADY PUBLISHED (for trend detection):
{hist.coverage_block(history)}

INTERNAL NOTE ON RETRIEVAL QUALITY (context for you; do not repeat it to the reader):
{corpus_assessment}

Write two things:

1. `analyst_note` — 2-3 sentences framing this week's launches. Talk about the LAUNCHES, not about the article corpus. Earlier editions opened with "this was a notably thin week" twelve times out of fifteen; that phrasing is now banned. If the week genuinely was quiet, find something more useful to say about why, or lead with what the strongest entry teaches.

2. `pattern_watch` — 2-4 sentences on what's visible across the recent weeks above. A recurring tactic, a shift in framing, a playbook appearing repeatedly, a scoring trend. Reference specific prior weeks and companies. This is the part that compounds for a reader who reads every week, so make it genuinely observational rather than generic.
"""

    return structured(
        claude,
        prompt,
        _SYNTHESIS_SCHEMA,
        effort="high",
        label="synthesis",
    )


def build_launches_digest(
    tavily: TavilyClient,
    claude: anthropic.Anthropic,
    history: dict,
) -> dict:
    print("  pass 1: sweeping the week's coverage...")
    articles = _gather_candidates(tavily)
    print(f"  pass 1: {len(articles)} unique articles")

    if not articles:
        return {
            "analyst_note": "No launch coverage could be retrieved this week.",
            "pattern_watch": "",
            "entries": [],
        }

    shortlist = _shortlist(claude, articles, history)
    # The schema can't express a cap, so enforce it here as well as in the prompt.
    candidates = shortlist.get("candidates", [])[:MAX_ENTRIES]
    print(f"  pass 1: shortlisted {len(candidates)}")

    entries = []
    for i, candidate in enumerate(candidates, 1):
        name = f"{candidate.get('company')} — {candidate.get('launch_name')}"
        print(f"  pass 2 ({i}/{len(candidates)}): researching {name}")
        sources = _research(tavily, candidate)
        print(f"    {len(sources)} primary source(s)")
        try:
            entries.append(_analyze(claude, candidate, sources))
        except StructureError as e:
            print(f"    dropped ({e})", file=sys.stderr)

    # Best first; unassessable entries last.
    entries.sort(key=lambda e: (e.get("score") is None, -(e.get("score") or 0)))

    synthesis = _synthesize(
        claude, entries, history, shortlist.get("corpus_assessment", "")
    )

    return {
        "analyst_note": synthesis.get("analyst_note", ""),
        "pattern_watch": synthesis.get("pattern_watch", ""),
        "entries": entries,
    }
