"""Command line entry point.

    python -m agent draft                       # add today's drafts (her profile, and the company page if on)
    python -m agent new-draft [--account company]  # add another draft now, even if today's exists
    python -m agent publish                     # publish rows marked Approved
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings, load_profile
from .daily_post import accounts, draft_daily_post, publish_approved
from .llm import get_llm
from .store import COMPANY, PROFILE, get_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent")
    parser.add_argument("command", choices=["draft", "new-draft", "publish"])
    parser.add_argument("--profile", help="Path to company.yaml (default: config/company.yaml)")
    parser.add_argument(
        "--account", choices=["profile", "company"], default="profile", help="Who new-draft writes for"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings.from_env()
    profile = load_profile(args.profile)
    settings.timezone = profile["schedule"]["timezone"]
    store = get_store(settings)

    if args.command in ("draft", "new-draft"):
        llm = get_llm(settings)
        if args.command == "new-draft":
            targets, manual = [COMPANY if args.account == "company" else PROFILE], True
        else:
            targets, manual = accounts(profile, store), False
        for account in targets:
            row = draft_daily_post(settings, profile, store, llm, manual=manual, account=account)
            if row:
                print(f"\nDraft saved for review, {account} ({row.topic}):\n\n{row.text}\n")
    else:
        published = publish_approved(settings, profile, store)
        print(f"Published {len(published)} post(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
