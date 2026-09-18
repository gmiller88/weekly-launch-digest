"""Render digest data to HTML.

The model returns structured data; all presentation lives here. Two targets:
the web page uses CSS classes, email uses inline styles because Gmail strips
<style> blocks.
"""

import html

_ROWS = [
    ("company_blurb", "Company"),
    ("the_launch", "The Launch"),
    ("product_fit", "Product Fit"),
    ("launch_playbook", "Launch Playbook"),
    ("messaging", "Messaging"),
    ("why_this_rating", "Why This Rating"),
]

# Inline styles for the email target, keyed to the same names as the web CSS.
_E = {
    "item": "margin-bottom: 32px; padding-bottom: 32px; border-bottom: 1px solid #eee;",
    "head": "margin-bottom: 12px;",
    "title": "margin: 0; font-size: 17px; font-weight: 600; color: #1a1a2e;",
    "score": (
        "display: inline-block; background: #0055cc; color: white; padding: 3px 10px;"
        " border-radius: 20px; font-size: 13px; font-weight: 700; white-space: nowrap;"
    ),
    "score_na": (
        "display: inline-block; background: #777; color: white; padding: 3px 10px;"
        " border-radius: 20px; font-size: 12px; font-weight: 700; white-space: nowrap;"
    ),
    "table": "width: 100%; border-collapse: collapse; font-size: 14px; line-height: 1.65;",
    "th": (
        "padding: 6px 12px 6px 0; vertical-align: top; white-space: nowrap;"
        " color: #555; font-weight: 600; width: 130px; text-align: left;"
    ),
    "td": "padding: 6px 0; color: #333;",
    "steal": (
        "margin-top: 14px; padding: 12px 14px; background: #f2f7f4;"
        " border-left: 3px solid #007744; border-radius: 4px;"
        " font-size: 14px; line-height: 1.6; color: #234;"
    ),
    "steal_label": (
        "font-size: 10px; font-weight: 700; letter-spacing: 1.1px;"
        " text-transform: uppercase; color: #007744; display: block; margin-bottom: 4px;"
    ),
    "evidence": "margin-top: 10px; font-size: 12px; color: #888; line-height: 1.55;",
    "note": (
        "font-style: italic; color: #555; margin-bottom: 20px;"
        " font-size: 14px; line-height: 1.7;"
    ),
    "pattern": (
        "margin-bottom: 24px; padding: 14px 16px; background: #f7f7fb;"
        " border-left: 3px solid #0055cc; border-radius: 4px;"
        " font-size: 14px; line-height: 1.7; color: #333;"
    ),
    "pattern_label": (
        "font-size: 10px; font-weight: 700; letter-spacing: 1.1px;"
        " text-transform: uppercase; color: #0055cc; display: block; margin-bottom: 4px;"
    ),
    "links": "margin-top: 10px; font-size: 13px;",
    "link": "color: #0055cc; text-decoration: none;",
    "empty": "color: #666; font-size: 14px;",
    "fund_item": "margin-bottom: 24px; padding-bottom: 24px; border-bottom: 1px solid #eee;",
    "fund_title": "margin: 0 0 8px; font-size: 16px; font-weight: 600; color: #1a1a2e;",
    "fund_body": "margin: 0 0 10px; line-height: 1.65; color: #333; font-size: 14px;",
    "track_btn": (
        "display: inline-block; margin-top: 14px; background: #ffffff;"
        " border: 1px solid #0055cc; color: #0055cc; font-size: 12px;"
        " font-weight: 600; padding: 7px 13px; border-radius: 5px;"
        " text-decoration: none;"
    ),
    "trk_item": (
        "margin-bottom: 18px; padding: 14px 16px; background: #fbfaf6;"
        " border-left: 3px solid #b8860b; border-radius: 4px;"
    ),
    "trk_head": (
        "font-size: 15px; font-weight: 600; color: #1a1a2e; margin: 0 0 6px;"
    ),
    "trk_badge": (
        "display: inline-block; background: #b8860b; color: #fff; padding: 2px 8px;"
        " border-radius: 20px; font-size: 11px; font-weight: 700;"
        " text-transform: uppercase; letter-spacing: 0.6px;"
    ),
    "trk_meta": "font-size: 11px; color: #887; margin-bottom: 8px;",
    "trk_headline": "font-size: 14px; line-height: 1.65; color: #333; margin: 0;",
}

# Momentum values, worst to best, with the colour used for the badge.
_MOMENTUM = {
    "accelerating": "#007744",
    "sustained": "#0055cc",
    "decaying": "#b8860b",
    "abandoned": "#c0392b",
    "unclear": "#777777",
}


def _esc(text) -> str:
    return html.escape(str(text or "").strip())


def _attr(name: str, email: bool) -> str:
    """Emit either a class attribute (web) or an inline style (email)."""
    if email:
        return f' style="{_E[name]}"' if name in _E else ""
    return f' class="d-{name.replace("_", "-")}"'


def _score_badge(entry: dict, email: bool) -> str:
    if not entry.get("assessable", True) or entry.get("score") is None:
        return f'<span{_attr("score_na", email)}>Not assessable</span>'
    score = entry["score"]
    text = f"{score:g}/10"
    return f'<span{_attr("score", email)}>{_esc(text)}</span>'


def _sources(entry: dict, email: bool) -> str:
    sources = [s for s in entry.get("sources", []) if s.get("url")]
    if not sources:
        return ""
    links = " &nbsp;·&nbsp; ".join(
        f'<a href="{_esc(s["url"])}"{_attr("link", email)}>'
        f'{_esc(s.get("title") or "Source")} &rarr;</a>'
        for s in sources[:4]
    )
    return f'<div{_attr("links", email)}>{links}</div>'


def _track_button(entry: dict, digest_date: str | None) -> str:
    """Email-only: a link that opens a pre-filled tracking issue.

    Web pages get the 'Discuss in Claude' affordance instead; the ask was for
    this to live in the email.
    """
    if not digest_date:
        return ""
    from . import tracking

    url = tracking.track_button_url(entry, digest_date)
    if not url:
        return ""
    return (
        f'<div style="margin-top: 4px;">'
        f'<a href="{_esc(url)}"{_attr("track_btn", True)}>'
        f"Track this launch &rarr;</a></div>"
    )


def _launch_entry(entry: dict, email: bool, digest_date: str | None = None) -> str:
    rows = []
    for key, label in _ROWS:
        value = entry.get(key)
        if not value:
            continue
        rows.append(
            f"<tr><td{_attr('th', email)}>{_esc(label)}</td>"
            f"<td{_attr('td', email)}>{_esc(value)}</td></tr>"
        )

    title = _esc(entry.get("company", ""))
    if entry.get("launch_name"):
        title += f" &mdash; {_esc(entry['launch_name'])}"

    parts = [
        f"<div{_attr('item', email)}>",
        f"<div{_attr('head', email)}>",
        f"<h3{_attr('title', email)}>{title}</h3>",
        _score_badge(entry, email),
        "</div>",
        f"<table{_attr('table', email)}>{''.join(rows)}</table>",
    ]

    if entry.get("steal_this"):
        parts.append(
            f"<div{_attr('steal', email)}>"
            f"<span{_attr('steal_label', email)}>Steal This</span>"
            f"{_esc(entry['steal_this'])}</div>"
        )

    if entry.get("evidence_note"):
        parts.append(
            f"<div{_attr('evidence', email)}>Evidence: {_esc(entry['evidence_note'])}</div>"
        )

    parts.append(_sources(entry, email))
    if email:
        parts.append(_track_button(entry, digest_date))
    parts.append("</div>")
    return "".join(parts)


def render_launches(
    data: dict, email: bool = False, digest_date: str | None = None
) -> str:
    entries = data.get("entries", [])
    out = []

    if data.get("analyst_note"):
        out.append(
            f"<p{_attr('note', email)}><strong>Analyst Note:</strong> "
            f"{_esc(data['analyst_note'])}</p>"
        )

    if data.get("pattern_watch"):
        out.append(
            f"<div{_attr('pattern', email)}>"
            f"<span{_attr('pattern_label', email)}>Pattern Watch</span>"
            f"{_esc(data['pattern_watch'])}</div>"
        )

    if not entries:
        out.append(
            f'<p{_attr("empty", email)}>No B2B product launches cleared the bar '
            f"this week.</p>"
        )
    else:
        out.extend(_launch_entry(e, email, digest_date) for e in entries)

    return "\n".join(out)


def render_tracking_summary(updates: list[dict], email: bool = False) -> str:
    """Compact per-launch summary: momentum + the single biggest development."""
    if not updates:
        return ""

    out = []
    for u in updates:
        momentum = (u.get("momentum") or "unclear").lower()
        colour = _MOMENTUM.get(momentum, "#777777")
        badge_style = _E["trk_badge"].replace("#b8860b", colour)
        badge = (
            f'<span style="{badge_style}">{_esc(momentum)}</span>'
            if email
            else f'<span class="d-trk-badge d-trk-{_esc(momentum)}">{_esc(momentum)}</span>'
        )

        title = _esc(u.get("company", ""))
        if u.get("launch_name"):
            title += f" &mdash; {_esc(u['launch_name'])}"

        meta = f"Week {u.get('week', '?')} &middot; first profiled {_esc(u.get('anchor_date', ''))}"
        if u.get("sustained_score") is not None:
            meta += (
                f" &middot; sustained-GTM {u['sustained_score']:g}/10"
                f" (launch moment {u.get('original_score')})"
            )

        out.append(
            f"<div{_attr('trk_item', email)}>"
            f"<div{_attr('trk_head', email)}>{title} &nbsp;{badge}</div>"
            f"<div{_attr('trk_meta', email)}>{meta}</div>"
            f"<p{_attr('trk_headline', email)}>{_esc(u.get('headline', ''))}</p>"
            f"</div>"
        )
    return "\n".join(out)


def render_tracking_full(update: dict, email: bool = False) -> str:
    """The complete dossier for one checkpoint, for the web page."""
    rows = []
    for key, label in (
        ("shipped_vs_promised", "Shipped vs promised"),
        ("channel_activity", "Channel activity"),
        ("third_party_validation", "Third-party validation"),
        ("messaging_evolution", "Messaging evolution"),
        ("hiring_signal", "Hiring signal"),
    ):
        if update.get(key):
            rows.append(
                f"<tr><td{_attr('th', email)}>{_esc(label)}</td>"
                f"<td{_attr('td', email)}>{_esc(update[key])}</td></tr>"
            )

    parts = [render_tracking_summary([update], email)]
    if rows:
        parts.append(f"<table{_attr('table', email)}>{''.join(rows)}</table>")
    if update.get("steal_this"):
        parts.append(
            f"<div{_attr('steal', email)}>"
            f"<span{_attr('steal_label', email)}>Steal This &mdash; Sustained GTM</span>"
            f"{_esc(update['steal_this'])}</div>"
        )
    if update.get("score_rationale"):
        label = (
            "Why this sustained score"
            if update.get("sustained_score") is not None
            else "What would make this strong by week 12"
        )
        parts.append(
            f"<div{_attr('evidence', email)}><strong>{label}:</strong> "
            f"{_esc(update['score_rationale'])}</div>"
        )
    parts.append(_sources(update, email))
    return "\n".join(parts)


def render_funding(data: dict, email: bool = False) -> str:
    entries = data.get("entries", [])
    if not entries:
        return (
            f'<p{_attr("empty", email)}>No confirmed top-tier VC-backed B2B '
            f"software rounds this week.</p>"
        )

    out = []
    for entry in entries:
        body = [
            f"<div{_attr('fund_item', email)}>",
            f"<h3{_attr('fund_title', email)}>{_esc(entry.get('company', ''))}</h3>",
            f"<p{_attr('fund_body', email)}>{_esc(entry.get('summary', ''))}</p>",
        ]
        if entry.get("gtm_angle"):
            body.append(
                f"<div{_attr('steal', email)}>"
                f"<span{_attr('steal_label', email)}>Why It Matters To You</span>"
                f"{_esc(entry['gtm_angle'])}</div>"
            )
        if entry.get("url"):
            body.append(
                f'<div{_attr("links", email)}>'
                f'<a href="{_esc(entry["url"])}"{_attr("link", email)}>Read more &rarr;</a></div>'
            )
        body.append("</div>")
        out.append("".join(body))
    return "\n".join(out)


def plain_text(
    data_funding: dict, data_launches: dict, tracking_updates: list[dict] | None = None
) -> str:
    """Flat text of the whole digest, for the 'discuss in Claude' clipboard payload."""
    lines = []

    for u in tracking_updates or []:
        lines.append(
            f"\n[TRACKING — WEEK {u.get('week')}] {u.get('company')} — "
            f"{u.get('launch_name')} | momentum: {u.get('momentum')}"
        )
        lines.append(u.get("headline", ""))
        for key, label in (
            ("shipped_vs_promised", "Shipped vs promised"),
            ("channel_activity", "Channel activity"),
            ("third_party_validation", "Third-party validation"),
            ("messaging_evolution", "Messaging evolution"),
            ("hiring_signal", "Hiring signal"),
            ("steal_this", "Steal this (sustained GTM)"),
        ):
            if u.get(key):
                lines.append(f"{label}: {u[key]}")
        if u.get("sustained_score") is not None:
            lines.append(
                f"Sustained-GTM score: {u['sustained_score']:g}/10 "
                f"(launch moment: {u.get('original_score')})"
            )
    if tracking_updates:
        lines.append("")

    lines.append("--- VC FUNDING ANNOUNCEMENTS ---")
    for e in data_funding.get("entries", []):
        lines.append(f"\n{e.get('company', '')}")
        lines.append(e.get("summary", ""))
        if e.get("gtm_angle"):
            lines.append(f"Why it matters: {e['gtm_angle']}")

    lines.append("\n\n--- TOP B2B PRODUCT LAUNCHES ---")
    if data_launches.get("analyst_note"):
        lines.append(f"\nAnalyst Note: {data_launches['analyst_note']}")
    if data_launches.get("pattern_watch"):
        lines.append(f"\nPattern Watch: {data_launches['pattern_watch']}")

    for e in data_launches.get("entries", []):
        score = e.get("score")
        label = f"{score:g}/10" if score is not None else "not assessable"
        lines.append(f"\n\n{e.get('company', '')} — {e.get('launch_name', '')} [{label}]")
        for key, field_label in _ROWS:
            if e.get(key):
                lines.append(f"{field_label}: {e[key]}")
        if e.get("steal_this"):
            lines.append(f"Steal This: {e['steal_this']}")

    return "\n".join(lines)
