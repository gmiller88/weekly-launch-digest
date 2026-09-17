"""VC funding digest, scoped to what a B2B product marketer can actually use.

Earlier editions filtered only on "a top-tier VC was involved", which surfaced
nuclear reactors, copper mining, satellites and defence drones — accurate, but
noise for this reader. The filter is now sector-aware and capped, and each entry
carries a go-to-market angle rather than sitting disconnected from the launches.
"""

import sys

import anthropic
from tavily import TavilyClient

from . import history as hist
from .llm import structured

MAX_ENTRIES = 5

TOP_VCS = [
    "Sequoia Capital",
    "Andreessen Horowitz", "a16z",
    "Benchmark",
    "Kleiner Perkins",
    "Accel",
    "General Catalyst",
    "Lightspeed Venture Partners",
    "Bessemer Venture Partners",
    "Founders Fund",
    "GV", "Google Ventures",
    "Tiger Global",
    "Insight Partners",
    "Index Ventures",
    "Greylock Partners",
    "NEA",
]

_SEARCH_QUERIES = [
    "B2B SaaS startup funding round announced this week",
    "enterprise software Series A Series B funding this week",
    "AI infrastructure developer tools startup raised funding this week",
    "vertical SaaS fintech infrastructure funding round announcement",
]

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["entries"],
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["company", "summary", "gtm_angle", "url"],
                "properties": {
                    "company": {"type": "string"},
                    "summary": {
                        "type": "string",
                        "description": (
                            "3-5 sentences: round type and amount, valuation if "
                            "disclosed, the top-tier VC connection, and stated use "
                            "of funds. Facts only."
                        ),
                    },
                    "gtm_angle": {
                        "type": "string",
                        "description": (
                            "One or two sentences on why this matters to a B2B product "
                            "marketer specifically — what this company is likely to "
                            "bring to market next, who they now compete with, or what "
                            "the raise says about where budget is moving."
                        ),
                    },
                    "url": {"type": "string"},
                },
            },
        }
    },
}


def _gather_articles(tavily: TavilyClient) -> list[dict]:
    seen: set[str] = set()
    articles: list[dict] = []
    for query in _SEARCH_QUERIES:
        try:
            results = tavily.search(
                query=query,
                search_depth="advanced",
                topic="news",
                days=7,
                max_results=8,
            ).get("results", [])
        except Exception as e:
            print(f"  funding search failed ({query!r}): {e}", file=sys.stderr)
            continue
        for r in results:
            url = r.get("url")
            if url and url not in seen:
                seen.add(url)
                articles.append(r)
    return articles


def build_funding_digest(
    tavily: TavilyClient,
    claude: anthropic.Anthropic,
    history: dict,
) -> dict:
    articles = _gather_articles(tavily)
    if not articles:
        return {"entries": []}

    corpus = "\n\n---\n\n".join(
        f"TITLE: {a.get('title', '')}\nURL: {a.get('url', '')}\n"
        f"SUMMARY: {(a.get('content') or '')[:600]}"
        for a in articles
    )

    covered = hist.funding_exclusions(history)
    covered_block = ", ".join(covered) if covered else "(nothing yet)"

    prompt = f"""You are a VC funding analyst writing for a VP of Product Marketing at a B2B software company. They read this to know which companies are about to show up as competitors, partners, or category-definers — and where enterprise budget is moving.

From the articles below, identify companies that raised with clear, confirmed involvement from a top-tier VC firm — either leading the round or participating, including as a prior investor in a new round.

TOP-TIER VCs: {", ".join(TOP_VCS)}

SECTOR SCOPE — this is a filter earlier editions lacked, and it matters:
INCLUDE: B2B software, SaaS, enterprise AI, developer tools, data and cloud infrastructure, security, fintech infrastructure, vertical SaaS, B2B marketplaces.
EXCLUDE: space, defence hardware, mining and materials, energy generation, biotech and therapeutics, robotics hardware, consumer apps and consumer marketplaces. These are real companies and real rounds, but they teach this reader nothing about bringing B2B software to market.

ALREADY COVERED in recent weeks — skip these unless it is a genuinely new round:
{covered_block}

RULES:
- Maximum {MAX_ENTRIES} entries. This is a ceiling, not a quota — earlier editions ran to ten entries some weeks and one in others, which made the section unreadable. Rank by relevance to a B2B software product marketer and cut the rest.
- Only confirmed involvement. Skip anything speculative.
- Deduplicate hard. If several articles cover the same round, that is one entry.
- Use the most authoritative URL available for each entry.
- Write in plain, direct language. Do not include filler that editorially validates the raise — no "demonstrating continued investor confidence", "underscoring top-tier VC support", "signalling strong conviction", or anything similar. State facts.

ARTICLES:
{corpus}
"""

    data = structured(
        claude,
        prompt,
        _SCHEMA,
        effort="high",
        label="funding",
    )
    # The schema can't express a cap, so enforce it here as well as in the prompt.
    data["entries"] = data.get("entries", [])[:MAX_ENTRIES]
    return data
