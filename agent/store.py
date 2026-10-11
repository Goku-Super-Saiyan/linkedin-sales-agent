"""Where drafts live and where she approves them: a Google Sheet ("Posts" tab).

LocalStore keeps the same rows in a JSON file for tests and dry runs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Protocol

PENDING = "Pending review"
APPROVED = "Approved"
REJECTED = "Rejected"
PUBLISHING = "Publishing"
PUBLISHED = "Published"
FAILED = "Failed"
POST_MANUALLY = "Post manually"

# Where a post goes. Rows from before this column existed are her profile.
PROFILE = "Her profile"
COMPANY = "Company page"
ACCOUNTS = [PROFILE, COMPANY]

# What she can pick from the Status dropdown.
STATUS_CHOICES = [PENDING, APPROVED, REJECTED, POST_MANUALLY, PUBLISHING, PUBLISHED, FAILED]


@dataclass
class PostRow:
    id: str
    date: str
    status: str
    topic: str
    text: str
    sources: str = ""
    notes: str = ""
    linkedin_link: str = ""
    published_at: str = ""
    # When to publish, "YYYY-MM-DD HH:MM" in the schedule's timezone. Empty means as soon as approved.
    post_at: str = ""
    account: str = PROFILE
    # The line shown on the post's picture card. Empty means the post has no picture.
    picture: str = ""

    def is_status(self, status: str) -> bool:
        return self.status.strip().lower() == status.lower()

    @property
    def for_company(self) -> bool:
        return self.account.strip().lower() == COMPANY.lower()


# Sheet header for each PostRow field, in column order.
HEADERS = {
    "id": "ID",
    "date": "Date",
    "status": "Status",
    "topic": "Topic",
    "text": "Post text",
    "sources": "Sources",
    "notes": "Notes",
    "linkedin_link": "LinkedIn link",
    "published_at": "Published at",
    "post_at": "Post at",
    "account": "Account",
    "picture": "Picture",
}
FIELD_NAMES = [f.name for f in fields(PostRow)]


class Store(Protocol):
    def list_posts(self) -> list[PostRow]: ...

    def add_post(self, row: PostRow) -> None: ...

    def update_post(self, post_id: str, **changes: str) -> None: ...

    def get_settings(self) -> dict[str, str]: ...


class LocalStore:
    def __init__(self, path: str | Path, settings: dict[str, str] | None = None):
        self.path = Path(path)
        self.settings = settings or {}

    def get_settings(self) -> dict[str, str]:
        return dict(self.settings)

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, rows: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    def list_posts(self) -> list[PostRow]:
        return [PostRow(**{**r, "account": r.get("account") or PROFILE}) for r in self._load()]

    def add_post(self, row: PostRow) -> None:
        rows = self._load()
        rows.append(asdict(row))
        self._save(rows)

    def update_post(self, post_id: str, **changes: str) -> None:
        rows = self._load()
        for r in rows:
            if r["id"] == post_id:
                r.update(changes)
                self._save(rows)
                return
        raise KeyError(post_id)


class SheetStore:
    TAB = "Posts"
    SETTINGS_TAB = "Settings"

    def __init__(self, sheet_id: str, service_account_json: str):
        import gspread

        client = gspread.service_account_from_dict(json.loads(service_account_json))
        self.spreadsheet = client.open_by_key(sheet_id)
        self.ws = self._worksheet()

    def _worksheet(self):
        import gspread
        from gspread.utils import ValidationConditionType

        try:
            ws = self.spreadsheet.worksheet(self.TAB)
            # Sheets created before a column was added get the new header too.
            if ws.row_values(1) != list(HEADERS.values()):
                if ws.col_count < len(HEADERS):
                    ws.add_cols(len(HEADERS) - ws.col_count)
                ws.update([list(HEADERS.values())], "A1")
            return ws
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet(self.TAB, rows=1000, cols=len(HEADERS))
            ws.update([list(HEADERS.values())], "A1")
            ws.freeze(rows=1)
            ws.add_validation(
                "C2:C1000",
                ValidationConditionType.one_of_list,
                STATUS_CHOICES,
                showCustomUi=True,
            )
            return ws

    def get_settings(self) -> dict[str, str]:
        """Key/value rows from the Settings tab, which the dashboard writes. Empty if there is none."""
        import gspread

        try:
            rows = self.spreadsheet.worksheet(self.SETTINGS_TAB).get_all_values()
        except gspread.WorksheetNotFound:
            return {}
        return {r[0].strip(): r[1].strip() for r in rows[1:] if len(r) >= 2 and r[0].strip()}

    def _rows(self) -> list[list[str]]:
        return self.ws.get_all_values()[1:]

    def list_posts(self) -> list[PostRow]:
        posts = []
        for values in self._rows():
            values = (values + [""] * len(FIELD_NAMES))[: len(FIELD_NAMES)]
            if values[0]:
                row = dict(zip(FIELD_NAMES, values))
                row["account"] = row["account"] or PROFILE
                posts.append(PostRow(**row))
        return posts

    def add_post(self, row: PostRow) -> None:
        self.ws.append_row([getattr(row, f) for f in FIELD_NAMES], table_range="A1")

    def update_post(self, post_id: str, **changes: str) -> None:
        from gspread.utils import rowcol_to_a1

        for offset, values in enumerate(self._rows()):
            if values and values[0] == post_id:
                sheet_row = offset + 2
                for name, value in changes.items():
                    col = FIELD_NAMES.index(name) + 1
                    self.ws.update([[value]], rowcol_to_a1(sheet_row, col))
                return
        raise KeyError(post_id)


def get_store(settings) -> Store:
    if settings.sheet_id and settings.google_service_account_json:
        return SheetStore(settings.sheet_id, settings.google_service_account_json)
    if settings.local_store_path:
        return LocalStore(settings.local_store_path)
    raise RuntimeError(
        "No place to save drafts: set SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON, "
        "or LOCAL_STORE_PATH for a local test run."
    )
