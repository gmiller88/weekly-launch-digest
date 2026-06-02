import os
import sys

import anthropic
from dotenv import load_dotenv
from tavily import TavilyClient

from .email_sender import send_digest_email
from .fundraising import build_funding_digest
from .launches import build_launches_digest
from .page_generator import write_digest_page

load_dotenv(override=True)

_REQUIRED_ENV = [
    "ANTHROPIC_API_KEY",
    "TAVILY_API_KEY",
    "GMAIL_USER",
    "GMAIL_APP_PASSWORD",
    "RECIPIENT_EMAIL",
]


def main() -> None:
    missing = [k for k in _REQUIRED_ENV if not os.getenv(k)]
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    print("Gathering VC funding news...")
    try:
        funding_html = build_funding_digest(tavily, claude)
    except Exception as e:
        print(f"WARNING: Funding digest failed: {e}", file=sys.stderr)
        funding_html = '<p style="color: #c00;">Funding digest unavailable this week due to an error.</p>'

    print("Gathering B2B product launch news...")
    try:
        launches_html = build_launches_digest(tavily, claude)
    except Exception as e:
        print(f"WARNING: Launches digest failed: {e}", file=sys.stderr)
        launches_html = '<p style="color: #c00;">Launches digest unavailable this week due to an error.</p>'

    print("Writing digest page...")
    write_digest_page(funding_html, launches_html)

    print("Sending email...")
    send_digest_email(
        gmail_user=os.environ["GMAIL_USER"],
        gmail_app_password=os.environ["GMAIL_APP_PASSWORD"],
        recipient=os.environ["RECIPIENT_EMAIL"],
        funding_html=funding_html,
        launches_html=launches_html,
        site_url=os.getenv("SITE_URL"),
    )
    print("Digest sent successfully.")


if __name__ == "__main__":
    main()
