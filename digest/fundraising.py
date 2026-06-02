import anthropic
from tavily import TavilyClient

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
    "startup funding round announced this week venture capital",
    "Series A Series B funding announcement this week tech startup",
    "raised million funding Sequoia a16z Benchmark Accel Kleiner",
    "venture capital investment startup funding announcement this week",
]


def _gather_articles(tavily: TavilyClient) -> list[dict]:
    seen: set[str] = set()
    articles: list[dict] = []
    for query in _SEARCH_QUERIES:
        resp = tavily.search(
            query=query,
            search_depth="advanced",
            topic="news",
            days=7,
            max_results=8,
        )
        for r in resp.get("results", []):
            if r["url"] not in seen:
                seen.add(r["url"])
                articles.append(r)
    return articles


def build_funding_digest(tavily: TavilyClient, claude: anthropic.Anthropic) -> str:
    articles = _gather_articles(tavily)
    if not articles:
        return '<p style="color: #666;">No funding announcements found this week.</p>'

    articles_block = "\n\n---\n\n".join(
        f"TITLE: {a['title']}\nURL: {a['url']}\nSUMMARY: {a['content'][:600]}"
        for a in articles
    )

    prompt = f"""You are a VC funding analyst. Review these news articles from the past 7 days and identify startups that received investment from a top-tier VC firm, OR raised a new round where a previous investor was a top-tier VC.

TOP-TIER VCs to look for: {", ".join(TOP_VCS)}

ARTICLES:
{articles_block}

Instructions:
- Only include companies with clear, confirmed top-tier VC involvement — skip anything speculative
- For each qualifying company, write 3-5 sentences covering: round type and amount raised, new valuation if disclosed, the top-tier VC connection (lead or notable participant), and stated use of funds
- Use the URL of the press release or most authoritative article for each entry
- Write in plain, direct language. Do not include generic filler phrases like "demonstrating continued investor confidence," "underscoring top-tier VC support," "signaling strong investor conviction," or any similar language that editorially validates the raise rather than describing it. Stick to facts.

Return HTML using exactly this structure for each company:

<div class="funding-item" style="margin-bottom: 24px; padding-bottom: 24px; border-bottom: 1px solid #eee;">
  <h3 style="margin: 0 0 8px; font-size: 16px; font-weight: 600; color: #1a1a2e;">COMPANY NAME</h3>
  <p style="margin: 0 0 10px; line-height: 1.65; color: #333; font-size: 14px;">SUMMARY SENTENCES</p>
  <a href="URL" style="color: #0055cc; font-size: 13px; text-decoration: none;">Read more →</a>
</div>

If no qualifying announcements exist this week, return only:
<p style="color: #666; font-size: 14px;">No confirmed top-tier VC-backed funding announcements this week.</p>"""

    msg = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text
