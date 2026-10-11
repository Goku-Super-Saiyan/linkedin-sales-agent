"""Loads the company profile (config/company.yaml) and runtime settings (environment)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = ROOT / "config" / "company.yaml"


def load_profile(path: Path | str | None = None) -> dict:
    with open(path or DEFAULT_PROFILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class Settings:
    """Runtime settings. Secrets come from environment variables, never from files in the repo."""

    llm_provider: str = "gemini"
    llm_model: str | None = None
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    sheet_id: str | None = None
    google_service_account_json: str | None = None
    local_store_path: str | None = None
    linkedin_access_token: str | None = None
    linkedin_person_urn: str | None = None
    linkedin_token_expires_on: date | None = None
    # The company page. Its token needs w_organization_social (Community Management API).
    linkedin_org_urn: str | None = None
    linkedin_org_access_token: str | None = None
    linkedin_org_token_expires_on: date | None = None
    timezone: str = "Asia/Kolkata"
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Settings":
        env = os.environ if env is None else env
        expires = env.get("LINKEDIN_TOKEN_EXPIRES_ON") or None
        org_expires = env.get("LINKEDIN_ORG_TOKEN_EXPIRES_ON") or None
        return cls(
            llm_provider=(env.get("LLM_PROVIDER") or "gemini").strip().lower(),
            llm_model=env.get("LLM_MODEL") or None,
            gemini_api_key=env.get("GEMINI_API_KEY") or None,
            anthropic_api_key=env.get("ANTHROPIC_API_KEY") or None,
            sheet_id=env.get("SHEET_ID") or None,
            google_service_account_json=env.get("GOOGLE_SERVICE_ACCOUNT_JSON") or None,
            local_store_path=env.get("LOCAL_STORE_PATH") or None,
            linkedin_access_token=env.get("LINKEDIN_ACCESS_TOKEN") or None,
            linkedin_person_urn=env.get("LINKEDIN_PERSON_URN") or None,
            linkedin_token_expires_on=date.fromisoformat(expires) if expires else None,
            linkedin_org_urn=env.get("LINKEDIN_ORG_URN") or None,
            linkedin_org_access_token=env.get("LINKEDIN_ORG_ACCESS_TOKEN") or None,
            linkedin_org_token_expires_on=date.fromisoformat(org_expires) if org_expires else None,
        )

    @property
    def linkedin_configured(self) -> bool:
        return bool(self.linkedin_access_token and self.linkedin_person_urn)

    @property
    def company_configured(self) -> bool:
        return bool(self.linkedin_org_access_token and self.linkedin_org_urn)

    def now(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone))
