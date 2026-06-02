import anthropic
from tavily import TavilyClient

_SEARCH_QUERIES = [
    "B2B software product launch announcement this week",
    "SaaS startup new product launch press release this week",
    "enterprise software launch keynote announcement this week",
    "startup product launch Product Hunt Hacker News viral this week",
    "B2B platform new feature launch announcement this week",
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


def build_launches_digest(tavily: TavilyClient, claude: anthropic.Anthropic) -> str:
    articles = _gather_articles(tavily)
    if not articles:
        return '<p style="color: #666;">No significant B2B product launches found this week.</p>'

    articles_block = "\n\n---\n\n".join(
        f"TITLE: {a['title']}\nURL: {a['url']}\nSUMMARY: {a['content'][:700]}"
        for a in articles
    )

    prompt = f"""You are an expert B2B Product Marketing strategist with deep experience analyzing software launches. Review these news articles from the past 7 days and identify the top 3 most impactful B2B software product launches.

Begin your response with a brief "Analyst Note" (2-3 sentences) commenting on the overall quality or theme of this week's launches — e.g. whether it was a strong week, a slow week, a week dominated by a particular trend or category, anything worth flagging as context before the individual entries. Format it as:
<p style="font-style: italic; color: #555; margin-bottom: 24px; font-size: 14px;"><strong>Analyst Note:</strong> YOUR NOTE HERE</p>

WHAT QUALIFIES:
- Net-new products or product lines
- Major new features launched with a dedicated campaign (not just a changelog entry)
- Platform expansions that open a new market or category

SELECTION CRITERIA — prioritize in this order:
1. Tier-1 media coverage: TechCrunch, The Verge, WSJ Tech, Forbes, Bloomberg Tech, or relevant trade publications
2. Conference keynote slot: Dreamforce, AWS re:Invent, Google Cloud Next, Snowflake Summit, Gartner, etc.
3. Community/social buzz: viral on LinkedIn, trending on Hacker News (#1-5), featured on Product Hunt front page
4. Strategic market impact: creates a new category, disrupts incumbents, or meaningfully shifts the competitive landscape
5. Marquee customer or partner announcements alongside the launch

COMPANY SCOPE: Prioritize startups and growth-stage companies. Include enterprise incumbents (Salesforce, Microsoft, etc.) only if the launch execution or market impact is truly exceptional.

ARTICLES:
{articles_block}

For each of the top 3 launches, return HTML using exactly this structure:

<div class="launch-item" style="margin-bottom: 32px; padding-bottom: 32px; border-bottom: 1px solid #eee;">
  <div style="display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 12px;">
    <h3 style="margin: 0; font-size: 17px; font-weight: 600; color: #1a1a2e; flex: 1;">COMPANY NAME — LAUNCH NAME</h3>
    <span style="display: inline-block; background: #0055cc; color: white; padding: 3px 10px; border-radius: 20px; font-size: 13px; font-weight: 700; margin-left: 12px; white-space: nowrap;">SCORE/10</span>
  </div>

  <table style="width: 100%; border-collapse: collapse; font-size: 14px; line-height: 1.65;">
    <tr>
      <td style="padding: 6px 12px 6px 0; vertical-align: top; white-space: nowrap; color: #555; font-weight: 600; width: 130px;">Company</td>
      <td style="padding: 6px 0; color: #333;">1-2 sentence company blurb: what they do and approximate stage/scale</td>
    </tr>
    <tr style="background: #fafafa;">
      <td style="padding: 6px 12px 6px 0; vertical-align: top; white-space: nowrap; color: #555; font-weight: 600;">The Launch</td>
      <td style="padding: 6px 0; color: #333;">What exactly launched and the core value proposition in plain terms</td>
    </tr>
    <tr>
      <td style="padding: 6px 12px 6px 0; vertical-align: top; white-space: nowrap; color: #555; font-weight: 600;">Product Fit</td>
      <td style="padding: 6px 0; color: #333;">How this fits their existing product suite and plays to their strengths — or where it's a stretch</td>
    </tr>
    <tr style="background: #fafafa;">
      <td style="padding: 6px 12px 6px 0; vertical-align: top; white-space: nowrap; color: #555; font-weight: 600;">Launch Playbook</td>
      <td style="padding: 6px 0; color: #333;">The specific channels and tactics used: conference slot, press embargo, influencer seeding, free tier hook, viral mechanic, waitlist, video demo, customer co-announcement, etc.</td>
    </tr>
    <tr>
      <td style="padding: 6px 12px 6px 0; vertical-align: top; white-space: nowrap; color: #555; font-weight: 600;">Messaging</td>
      <td style="padding: 6px 0; color: #333;">How they positioned it — the narrative angle, what they emphasized, notable framing choices, what they deliberately left unsaid</td>
    </tr>
    <tr style="background: #fafafa;">
      <td style="padding: 6px 12px 6px 0; vertical-align: top; white-space: nowrap; color: #555; font-weight: 600;">Why This Rating</td>
      <td style="padding: 6px 0; color: #333;">2-3 sentences on what drove the score — specific things they did exceptionally well or where they left impact on the table</td>
    </tr>
  </table>

  <div style="margin-top: 10px;">
    <a href="URL" style="color: #0055cc; font-size: 13px; text-decoration: none;">Read more →</a>
  </div>
</div>

RATING GUIDE (1-10, PMM execution lens — not product quality alone):
- 10: Near-flawless execution, outsized buzz relative to effort, strong narrative, clear activation strategy
- 7-9: Solid execution with at least one standout element (great messaging, smart channel mix, strong timing)
- 4-6: Competent but unremarkable — launch happened, press was picked up, but nothing distinctive
- 1-3: Missed opportunities, muddled messaging, weak distribution, or launch underwhelmed given the product quality

Do not pad the list with minor releases. If fewer than 3 genuinely strong launches exist this week, include only those that qualify and note that it was a slower week."""

    msg = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text
