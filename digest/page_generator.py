import glob
import os
import re
from datetime import datetime

from . import render


def _escape_for_js_template(text: str) -> str:
    """Escape text for safe embedding in a JS template literal."""
    text = text.replace("\\", "\\\\")
    text = text.replace("`", "\\`")
    text = text.replace("${", "\\${")
    return text


_STYLE = """\
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    html, body {
      min-height: 100%;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      background: #f0f2f5;
      color: #1a1a2e;
    }

    #page { max-width: 740px; margin: 0 auto; padding: 0 16px 48px; }

    /* Header */
    #digest-header {
      background: #1a1a2e;
      margin: 0 -16px;
      padding: 24px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }

    #digest-header h1 {
      font-size: 19px;
      font-weight: 700;
      color: #fff;
      letter-spacing: -0.3px;
    }

    #digest-header .date { font-size: 12px; color: #8888aa; margin-top: 3px; }

    #digest-header .archive-link {
      display: inline-block;
      margin-top: 8px;
      font-size: 12px;
      color: #8899cc;
      text-decoration: none;
    }

    #digest-header .archive-link:hover { color: #aabbee; }

    /* Open in Claude button */
    #claude-btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: #0055cc;
      color: #fff;
      border: none;
      border-radius: 7px;
      padding: 9px 16px;
      font-size: 13px;
      font-weight: 600;
      font-family: inherit;
      cursor: pointer;
      white-space: nowrap;
      transition: background 0.15s;
      flex-shrink: 0;
    }

    #claude-btn:hover { background: #0044aa; }
    #claude-btn.copied { background: #007744; cursor: default; }
    #claude-btn svg { width: 14px; height: 14px; flex-shrink: 0; }

    #copy-hint {
      font-size: 11px;
      color: #8888aa;
      margin-top: 6px;
      text-align: right;
      display: none;
    }

    #copy-hint.visible { display: block; }

    /* Sections */
    .digest-section {
      background: white;
      border-radius: 8px;
      padding: 24px 28px;
      margin-top: 20px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.07);
    }

    .section-label {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 1.2px;
      text-transform: uppercase;
      margin-bottom: 18px;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .section-label::before {
      content: "";
      display: inline-block;
      width: 3px;
      height: 14px;
      border-radius: 2px;
    }

    .section-label.funding { color: #0055cc; }
    .section-label.funding::before { background: #0055cc; }
    .section-label.launches { color: #007744; }
    .section-label.launches::before { background: #007744; }
    .section-label.tracking { color: #b8860b; }
    .section-label.tracking::before { background: #b8860b; }

    /* Post-launch tracking */
    .d-trk-item {
      margin-bottom: 18px;
      padding: 14px 16px;
      background: #fbfaf6;
      border-left: 3px solid #b8860b;
      border-radius: 4px;
    }

    .d-trk-head { font-size: 15px; font-weight: 600; color: #1a1a2e; margin: 0 0 6px; }
    .d-trk-meta { font-size: 11px; color: #887; margin-bottom: 8px; }
    .d-trk-headline { font-size: 14px; line-height: 1.65; color: #333; margin: 0; }

    .d-trk-badge {
      display: inline-block;
      color: #fff;
      padding: 2px 8px;
      border-radius: 20px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.6px;
      background: #777;
    }

    .d-trk-accelerating { background: #007744; }
    .d-trk-sustained { background: #0055cc; }
    .d-trk-decaying { background: #b8860b; }
    .d-trk-abandoned { background: #c0392b; }
    .d-trk-unclear { background: #777; }

    .d-trk-block {
      margin-bottom: 34px;
      padding-bottom: 30px;
      border-bottom: 1px solid #eee;
    }

    .d-trk-block:last-child { margin-bottom: 0; padding-bottom: 0; border-bottom: none; }

    /* ── Digest content (targets from digest/render.py) ───────────── */

    .d-item {
      margin-bottom: 32px;
      padding-bottom: 32px;
      border-bottom: 1px solid #eee;
    }

    .d-item:last-child, .d-fund-item:last-child {
      margin-bottom: 0;
      padding-bottom: 0;
      border-bottom: none;
    }

    .d-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }

    .d-title {
      margin: 0;
      font-size: 17px;
      font-weight: 600;
      color: #1a1a2e;
      flex: 1;
      line-height: 1.4;
    }

    .d-score, .d-score-na {
      display: inline-block;
      color: white;
      padding: 3px 10px;
      border-radius: 20px;
      font-weight: 700;
      white-space: nowrap;
      flex-shrink: 0;
    }

    .d-score { background: #0055cc; font-size: 13px; }
    .d-score-na { background: #777; font-size: 12px; }

    .d-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
      line-height: 1.65;
    }

    .d-th {
      padding: 6px 12px 6px 0;
      vertical-align: top;
      white-space: nowrap;
      color: #555;
      font-weight: 600;
      width: 130px;
      text-align: left;
    }

    .d-td { padding: 6px 0; color: #333; }
    .d-table tr:nth-child(even) { background: #fafafa; }

    .d-steal {
      margin-top: 14px;
      padding: 12px 14px;
      background: #f2f7f4;
      border-left: 3px solid #007744;
      border-radius: 4px;
      font-size: 14px;
      line-height: 1.6;
      color: #234;
    }

    .d-steal-label {
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 1.1px;
      text-transform: uppercase;
      color: #007744;
      display: block;
      margin-bottom: 4px;
    }

    .d-evidence {
      margin-top: 10px;
      font-size: 12px;
      color: #888;
      line-height: 1.55;
    }

    .d-note {
      font-style: italic;
      color: #555;
      margin-bottom: 20px;
      font-size: 14px;
      line-height: 1.7;
    }

    .d-pattern {
      margin-bottom: 24px;
      padding: 14px 16px;
      background: #f7f7fb;
      border-left: 3px solid #0055cc;
      border-radius: 4px;
      font-size: 14px;
      line-height: 1.7;
      color: #333;
    }

    .d-pattern-label {
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 1.1px;
      text-transform: uppercase;
      color: #0055cc;
      display: block;
      margin-bottom: 4px;
    }

    .d-links { margin-top: 10px; font-size: 13px; }
    .d-link { color: #0055cc; text-decoration: none; }
    .d-link:hover { text-decoration: underline; }
    .d-empty { color: #666; font-size: 14px; }

    .d-fund-item {
      margin-bottom: 24px;
      padding-bottom: 24px;
      border-bottom: 1px solid #eee;
    }

    .d-fund-title {
      margin: 0 0 8px;
      font-size: 16px;
      font-weight: 600;
      color: #1a1a2e;
    }

    .d-fund-body {
      margin: 0 0 10px;
      line-height: 1.65;
      color: #333;
      font-size: 14px;
    }

    /* Archive index */
    .archive-row {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      padding: 12px 0;
      border-bottom: 1px solid #eee;
    }

    .archive-row:last-child { border-bottom: none; }
    .archive-row a { color: #0055cc; text-decoration: none; font-weight: 600; font-size: 15px; }
    .archive-row a:hover { text-decoration: underline; }
    .archive-row .meta { font-size: 12px; color: #888; }

    @media (max-width: 560px) {
      .d-table, .d-table tbody, .d-table tr, .d-th, .d-td { display: block; width: auto; }
      .d-th { padding-bottom: 0; }
      .d-td { padding-top: 2px; padding-bottom: 10px; }
      .d-table tr:nth-child(even) { background: transparent; }
    }
"""

_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Weekly Launch Digest — DATE_PLACEHOLDER</title>
  <style>
STYLE_PLACEHOLDER  </style>
</head>
<body>
  <div id="page">

    <div id="digest-header">
      <div>
        <h1>Weekly Launch Digest</h1>
        <div class="date">Week ending DATE_PLACEHOLDER</div>
        <a class="archive-link" href="ARCHIVE_HREF_PLACEHOLDER">Browse past weeks &rarr;</a>
        <a class="archive-link" href="TRACKING_HREF_PLACEHOLDER" style="margin-left: 14px;">Tracked launches &rarr;</a>
      </div>
      <div>
        <button id="claude-btn" onclick="openInClaude()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          <span id="btn-label">Discuss in Claude.ai</span>
        </button>
        <div id="copy-hint">Digest copied &mdash; just paste into Claude.ai</div>
      </div>
    </div>

TRACKING_SECTION_PLACEHOLDER
    <div class="digest-section">
      <div class="section-label launches">Top B2B Product Launches</div>
      LAUNCHES_CONTENT_PLACEHOLDER
    </div>

    <div class="digest-section">
      <div class="section-label funding">VC Funding Announcements</div>
      FUNDING_CONTENT_PLACEHOLDER
    </div>

  </div>

  <script>
    const CONTEXT_PROMPT = `CONTEXT_PROMPT_PLACEHOLDER`;

    async function openInClaude() {
      const btn = document.getElementById('claude-btn');
      const label = document.getElementById('btn-label');
      const hint = document.getElementById('copy-hint');

      try {
        await navigator.clipboard.writeText(CONTEXT_PROMPT);
        btn.classList.add('copied');
        label.textContent = 'Copied!';
        hint.classList.add('visible');
      } catch (e) {
        // Clipboard blocked (e.g. non-HTTPS) — open Claude anyway
      }

      window.open('https://claude.ai', '_blank');

      setTimeout(() => {
        btn.classList.remove('copied');
        label.textContent = 'Discuss in Claude.ai';
        hint.classList.remove('visible');
      }, 4000);
    }
  </script>

</body>
</html>"""

_ARCHIVE_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Weekly Launch Digest — Archive</title>
  <style>
STYLE_PLACEHOLDER  </style>
</head>
<body>
  <div id="page">
    <div id="digest-header">
      <div>
        <h1>Weekly Launch Digest</h1>
        <div class="date">Archive &mdash; COUNT_PLACEHOLDER editions</div>
        <a class="archive-link" href="index.html">&larr; Latest edition</a>
      </div>
    </div>

    <div class="digest-section">
      <div class="section-label launches">Past Editions</div>
      ROWS_PLACEHOLDER
    </div>
  </div>
</body>
</html>"""


def _build_page(
    funding_html: str,
    launches_html: str,
    date_label: str,
    context_prompt: str,
    archive_href: str,
    tracking_href: str = "tracking.html",
    tracking_html: str = "",
) -> str:
    section = ""
    if tracking_html:
        section = (
            '    <div class="digest-section">\n'
            '      <div class="section-label tracking">Post-Launch Tracking</div>\n'
            f"      {tracking_html}\n"
            "    </div>\n"
        )
    return (
        _PAGE
        .replace("STYLE_PLACEHOLDER", _STYLE)
        .replace("DATE_PLACEHOLDER", date_label)
        .replace("ARCHIVE_HREF_PLACEHOLDER", archive_href)
        .replace("TRACKING_HREF_PLACEHOLDER", tracking_href)
        .replace("TRACKING_SECTION_PLACEHOLDER", section)
        .replace("FUNDING_CONTENT_PLACEHOLDER", funding_html)
        .replace("LAUNCHES_CONTENT_PLACEHOLDER", launches_html)
        .replace("CONTEXT_PROMPT_PLACEHOLDER", _escape_for_js_template(context_prompt))
    )


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def write_archive_index(output_dir: str = "docs") -> int:
    """Rebuild the archive index from the dated pages on disk."""
    paths = sorted(
        glob.glob(os.path.join(output_dir, "archive", "*.html")), reverse=True
    )

    rows = []
    for path in paths:
        iso = os.path.splitext(os.path.basename(path))[0]
        try:
            label = datetime.strptime(iso, "%Y-%m-%d").strftime("%B %d, %Y")
        except ValueError:
            label = iso

        html = ""
        try:
            with open(path, encoding="utf-8") as f:
                html = f.read()
        except OSError:
            pass

        # Tolerate both the current markup and the pre-rewrite inline-styled
        # pages that were backfilled into the archive.
        scores = [float(s) for s in re.findall(r">\s*([\d.]+)\s*/\s*10\s*<", html)]
        count = html.count('class="d-item"') + html.count('class="launch-item"')
        meta = f"{count} launch{'es' if count != 1 else ''}"
        if scores:
            meta += f" &middot; top score {max(scores):g}/10"

        rows.append(
            f'<div class="archive-row">'
            f'<a href="archive/{iso}.html">{label}</a>'
            f'<span class="meta">{meta}</span>'
            f"</div>"
        )

    if not rows:
        rows = ['<p class="d-empty">No archived editions yet.</p>']

    page = (
        _ARCHIVE_PAGE
        .replace("STYLE_PLACEHOLDER", _STYLE)
        .replace("COUNT_PLACEHOLDER", str(len(paths)))
        .replace("ROWS_PLACEHOLDER", "\n      ".join(rows))
    )
    _write(os.path.join(output_dir, "archive.html"), page)
    return len(paths)


def write_tracking_page(
    updates: list[dict],
    date_label: str,
    output_dir: str = "docs",
) -> None:
    """Full dossiers for this week's checkpoints, linked from the email summary."""
    if updates:
        blocks = "\n".join(
            f'<div class="d-trk-block">{render.render_tracking_full(u)}</div>'
            for u in updates
        )
    else:
        blocks = (
            '<p class="d-empty">No tracking checkpoints were due this week. '
            'Press "Track this launch" in any digest email to start following one.</p>'
        )

    page = (
        _PAGE
        .replace("STYLE_PLACEHOLDER", _STYLE)
        .replace("DATE_PLACEHOLDER", date_label)
        .replace("ARCHIVE_HREF_PLACEHOLDER", "archive.html")
        .replace("TRACKING_HREF_PLACEHOLDER", "tracking.html")
        .replace("TRACKING_SECTION_PLACEHOLDER", "")
        .replace(
            '<div class="section-label launches">Top B2B Product Launches</div>',
            '<div class="section-label tracking">Post-Launch Tracking</div>',
        )
        .replace("LAUNCHES_CONTENT_PLACEHOLDER", blocks)
        .replace(
            '<div class="digest-section">\n      <div class="section-label funding">'
            "VC Funding Announcements</div>\n      FUNDING_CONTENT_PLACEHOLDER\n"
            "    </div>",
            "",
        )
        .replace("FUNDING_CONTENT_PLACEHOLDER", "")
        .replace("CONTEXT_PROMPT_PLACEHOLDER", "")
    )
    _write(os.path.join(output_dir, "tracking.html"), page)


def write_digest_page(
    funding: dict,
    launches: dict,
    date_label: str | None = None,
    date_iso: str | None = None,
    output_dir: str = "docs",
    tracking_updates: list[dict] | None = None,
) -> None:
    """Write this week's page, its permanent dated copy, and the archive index."""
    date_label = date_label or datetime.now().strftime("%B %d, %Y")
    date_iso = date_iso or datetime.now().strftime("%Y-%m-%d")
    tracking_updates = tracking_updates or []

    funding_html = render.render_funding(funding)
    launches_html = render.render_launches(launches)
    tracking_html = render.render_tracking_summary(tracking_updates)

    context_prompt = (
        f"You are a helpful assistant with deep expertise in B2B product marketing "
        f"and the startup ecosystem. I've just read my Weekly Launch Digest for the "
        f"week ending {date_label} and want to dig deeper on some of what I read. "
        f"Here's the full digest:\n\n"
        f"{render.plain_text(funding, launches, tracking_updates)}\n\n"
        f"I'll ask you follow-up questions."
    )

    # Permanent dated copy — the archive is the training material.
    _write(
        os.path.join(output_dir, "archive", f"{date_iso}.html"),
        _build_page(
            funding_html, launches_html, date_label, context_prompt,
            "../archive.html", "../tracking.html", tracking_html,
        ),
    )

    # Current edition.
    _write(
        os.path.join(output_dir, "index.html"),
        _build_page(
            funding_html, launches_html, date_label, context_prompt,
            "archive.html", "tracking.html", tracking_html,
        ),
    )

    write_tracking_page(tracking_updates, date_label, output_dir)

    total = write_archive_index(output_dir)
    print(f"  wrote index.html + archive/{date_iso}.html ({total} editions archived)")
