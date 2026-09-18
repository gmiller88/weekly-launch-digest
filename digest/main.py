import argparse
import json
import os
import sys

import anthropic
from dotenv import load_dotenv
from tavily import TavilyClient

from . import history as hist
from . import llm
from . import tracking
from .email_sender import send_digest_email
from .fundraising import build_funding_digest
from .launches import build_launches_digest
from .page_generator import write_digest_page

load_dotenv(override=True)

_REQUIRED_ENV = ["ANTHROPIC_API_KEY", "TAVILY_API_KEY"]
_EMAIL_ENV = ["GMAIL_USER", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAIL"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the weekly launch digest.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the page and history but don't send the email.",
    )
    parser.add_argument(
        "--dump",
        metavar="PATH",
        help="Also write the raw digest data as JSON, for inspection.",
    )
    args = parser.parse_args()

    required = _REQUIRED_ENV + ([] if args.dry_run else _EMAIL_ENV)
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(
            f"ERROR: Missing environment variables: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    date_label = hist.today_str()
    date_iso = hist.today_iso()
    history = hist.load_history()
    print(f"Loaded history: {len(history.get('weeks', []))} prior week(s)")

    print("Gathering B2B product launches...")
    try:
        launches = build_launches_digest(tavily, claude, history)
    except Exception as e:
        print(f"WARNING: Launches digest failed: {e}", file=sys.stderr)
        launches = {"analyst_note": "", "pattern_watch": "", "entries": []}

    print("Gathering VC funding news...")
    try:
        funding = build_funding_digest(tavily, claude, history)
    except Exception as e:
        print(f"WARNING: Funding digest failed: {e}", file=sys.stderr)
        funding = {"entries": []}

    print("Running post-launch tracking checkpoints...")
    try:
        tracking_updates = tracking.run_checkpoints(tavily, claude)
        print(f"  {len(tracking_updates)} checkpoint(s) this week")
    except Exception as e:
        print(f"WARNING: Tracking failed: {e}", file=sys.stderr)
        tracking_updates = []

    if not launches["entries"] and not funding["entries"]:
        print("ERROR: Both sections are empty — not publishing.", file=sys.stderr)
        sys.exit(1)

    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as f:
            json.dump(
                {"date": date_iso, "launches": launches, "funding": funding,
                 "tracking": tracking_updates},
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"Wrote raw data to {args.dump}")

    print("Writing digest page...")
    write_digest_page(
        funding, launches, date_label=date_label, date_iso=date_iso,
        tracking_updates=tracking_updates,
    )

    print("Recording history...")
    hist.save_history(hist.record_week(history, date_iso, launches, funding))

    if args.dry_run:
        print("Dry run — skipping email.")
    else:
        print("Sending email...")
        send_digest_email(
            gmail_user=os.environ["GMAIL_USER"],
            gmail_app_password=os.environ["GMAIL_APP_PASSWORD"],
            recipient=os.environ["RECIPIENT_EMAIL"],
            funding=funding,
            launches=launches,
            site_url=os.getenv("SITE_URL"),
            date_label=date_label,
            date_iso=date_iso,
            tracking_updates=tracking_updates,
        )

    scored = [e for e in launches["entries"] if e.get("score") is not None]
    print(
        f"Done. {len(launches['entries'])} launch(es) "
        f"({len(scored)} scored), {len(funding['entries'])} funding entr(ies)."
    )
    print(f"API usage: {llm.usage_summary()}")


if __name__ == "__main__":
    main()
