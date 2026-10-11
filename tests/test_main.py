import agent.__main__ as cli
from agent.store import COMPANY, PROFILE


def test_new_draft_for_both_writes_one_draft_per_account(monkeypatch):
    calls = []

    class FakeSettings:
        timezone = None

        @staticmethod
        def from_env():
            return FakeSettings()

    monkeypatch.setattr(cli, "Settings", FakeSettings)
    monkeypatch.setattr(cli, "load_profile", lambda path: {"schedule": {"timezone": "Asia/Kolkata"}})
    monkeypatch.setattr(cli, "get_store", lambda settings: None)
    monkeypatch.setattr(cli, "get_llm", lambda settings: None)
    monkeypatch.setattr(
        cli, "draft_daily_post", lambda *a, manual, account: calls.append((account, manual))
    )

    assert cli.main(["new-draft", "--account", "both"]) == 0
    assert calls == [(PROFILE, True), (COMPANY, True)]


def test_one_account_failing_still_drafts_the_other(monkeypatch):
    calls = []

    class FakeSettings:
        timezone = None

        @staticmethod
        def from_env():
            return FakeSettings()

    def draft(*a, manual, account):
        if account == PROFILE:
            raise RuntimeError("AI busy")
        calls.append(account)

    monkeypatch.setattr(cli, "Settings", FakeSettings)
    monkeypatch.setattr(cli, "load_profile", lambda path: {"schedule": {"timezone": "Asia/Kolkata"}})
    monkeypatch.setattr(cli, "get_store", lambda settings: None)
    monkeypatch.setattr(cli, "get_llm", lambda settings: None)
    monkeypatch.setattr(cli, "draft_daily_post", draft)

    assert cli.main(["new-draft", "--account", "both"]) == 1
    assert calls == [COMPANY]
