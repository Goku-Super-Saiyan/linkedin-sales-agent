"""Command line entry point.

    python -m agent draft      # research news and add today's draft to the sheet
    python -m agent new-draft  # add another draft now, even if today's exists
    python -m agent publish    # publish rows marked Approved
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings, load_profile
from .daily_post import draft_daily_post, publish_approved
from .llm import get_llm
from .store import get_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent")
    parser.add_argument("command", choices=["draft", "new-draft", "publish"])
    parser.add_argument("--profile", help="Path to company.yaml (default: config/company.yaml)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings.from_env()
    profile = load_profile(args.profile)
    settings.timezone = profile["schedule"]["timezone"]
    store = get_store(settings)

    if args.command in ("draft", "new-draft"):
        manual = args.command == "new-draft"
        row = draft_daily_post(settings, profile, store, get_llm(settings), manual=manual)
        if row:
            print(f"\nDraft saved for review ({row.topic}):\n\n{row.text}\n")
    else:
        published = publish_approved(settings, profile, store)
        print(f"Published {len(published)} post(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
