import pytest
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from agent import linkedin
from agent.config import load_profile
from agent.daily_post import accounts, draft_daily_post, picture_every, publish_approved, wants_picture
from agent.feeds import NewsItem
from agent.store import (
    COMPANY,
    PROFILE,
    APPROVED,
    FAILED,
    PENDING,
    POST_MANUALLY,
    PUBLISHED,
    PUBLISHING,
    PostRow,
)
from conftest import FakeLLM, good_post

NOW = datetime(2026, 10, 11, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def news(url="https://ex.com/a"):
    return NewsItem("Salesforce Agentforce news", url, "CRM", NOW.astimezone(timezone.utc) - timedelta(hours=5), "src")


@pytest.fixture
def profile():
    """The real profile, with every day set to news so these tests don't depend on the weekday."""
    profile = load_profile()
    for day in profile["content"]["weekly_plan"].values():
        day["source"] = "news"
    return profile


def reply(url="https://ex.com/a"):
    return {"topic": "Agentforce", "source_urls": [url], "post": good_post()}


def test_draft_adds_one_pending_row(settings, profile, store):
    row = draft_daily_post(settings, profile, store, FakeLLM(reply()), fetch=lambda _: [news()], now=NOW)
    assert row.status == PENDING
    assert row.date == "2026-10-11"
    assert row.sources == "https://ex.com/a"
    assert store.list_posts() == [row]


def test_draft_runs_once_per_day(settings, profile, store):
    draft_daily_post(settings, profile, store, FakeLLM(reply()), fetch=lambda _: [news()], now=NOW)
    again = draft_daily_post(settings, profile, store, FakeLLM(), fetch=lambda _: [news()], now=NOW)
    assert again is None
    assert len(store.list_posts()) == 1


def test_draft_skips_articles_already_used(settings, profile, store):
    store.add_post(PostRow("old", "2026-10-10", PUBLISHED, "t", "x", sources="https://ex.com/a"))
    llm = FakeLLM({"topic": "CRM", "source_urls": [], "post": good_post()})
    row = draft_daily_post(settings, profile, store, llm, fetch=lambda _: [news()], now=NOW)
    assert "evergreen" in row.notes


def test_draft_records_the_plan_in_notes(settings, profile, store):
    row = draft_daily_post(settings, profile, store, FakeLLM(reply()), fetch=lambda _: [news()], now=NOW)
    assert row.notes.startswith("Plan: Sunday, Point of view. Hook: Two paths over time.")


def test_evergreen_day_ignores_news(settings, store):
    profile = load_profile()  # Sunday is an evergreen day in the real plan.
    fetched = []
    llm = FakeLLM({"topic": "CRM", "source_urls": [], "post": good_post()})
    row = draft_daily_post(
        settings, profile, store, llm, fetch=lambda f: fetched.append(f) or [news()], now=NOW
    )
    assert fetched == []
    assert row.sources == ""
    assert "evergreen topic" in llm.prompts[0][1] and "Two paths over time" in llm.prompts[0][1]
    assert "No fresh" not in row.notes


def test_draft_notes_when_linkedin_not_connected(profile, store):
    from agent.config import Settings

    row = draft_daily_post(Settings(), profile, store, FakeLLM(reply()), fetch=lambda _: [news()], now=NOW)
    assert "LinkedIn isn't connected" in row.notes


def test_draft_warns_before_token_expires(settings, profile, store):
    settings.linkedin_token_expires_on = date(2026, 10, 15)
    row = draft_daily_post(settings, profile, store, FakeLLM(reply()), fetch=lambda _: [news()], now=NOW)
    assert "expires on 15 Oct" in row.notes


def approved(post_id="2026-10-11-post", day="2026-10-11"):
    return PostRow(post_id, day, APPROVED, "t", good_post())


def test_publish_posts_approved_row(settings, profile, store):
    store.add_post(approved())
    calls = []

    def fake_publish(token, urn, text, image):
        calls.append((token, urn, store.list_posts()[0].status))
        return "urn:li:share:1"

    assert publish_approved(settings, profile, store, publish=fake_publish, now=NOW) == ["urn:li:share:1"]
    # It was marked Publishing before the API call, so a crash can't double-post.
    assert calls == [("token", "urn:li:person:abc", PUBLISHING)]
    row = store.list_posts()[0]
    assert row.status == PUBLISHED
    assert row.linkedin_link == "https://www.linkedin.com/feed/update/urn:li:share:1/"


def test_publish_ignores_pending_and_rejected(settings, profile, store):
    store.add_post(PostRow("a", "2026-10-11", PENDING, "t", good_post()))
    store.add_post(PostRow("b", "2026-10-11", "rejected", "t", good_post()))
    assert publish_approved(settings, profile, store, publish=lambda *a: 1 / 0, now=NOW) == []


def test_publish_accepts_any_capitalisation(settings, profile, store):
    store.add_post(PostRow("a", "2026-10-11", " approved ", "t", good_post()))
    assert publish_approved(settings, profile, store, publish=lambda *a: "urn:li:share:2", now=NOW)


def test_publish_respects_daily_limit(settings, profile, store):
    store.add_post(approved("one", "2026-10-10"))
    store.add_post(approved("two", "2026-10-11"))
    published = publish_approved(settings, profile, store, publish=lambda *a: "urn:li:share:9", now=NOW)
    assert len(published) == 1
    rows = {r.id: r for r in store.list_posts()}
    assert rows["one"].status == PUBLISHED
    assert rows["two"].status == APPROVED
    assert "tomorrow" in rows["two"].notes


def test_publish_marks_failure_and_reauth(settings, profile, store):
    store.add_post(approved())

    def expired(*a):
        raise linkedin.LinkedInError("unauthorized", status=401)

    publish_approved(settings, profile, store, publish=expired, now=NOW)
    row = store.list_posts()[0]
    assert row.status == FAILED
    assert "expired" in row.notes


def test_publish_without_linkedin_asks_her_to_post_manually(profile, store):
    from agent.config import Settings

    store.add_post(approved())
    publish_approved(Settings(), profile, store, publish=lambda *a: 1 / 0, now=NOW)
    assert store.list_posts()[0].status == POST_MANUALLY


def test_publish_waits_for_post_at(settings, profile, store):
    row = approved()
    row.post_at = "2026-10-11 10:30"
    store.add_post(row)
    assert publish_approved(settings, profile, store, publish=lambda *a: 1 / 0, now=NOW) == []
    assert store.list_posts()[0].status == APPROVED


def test_publish_when_post_at_has_passed(settings, profile, store):
    row = approved()
    row.post_at = "2026-10-11T07:45"
    store.add_post(row)
    assert publish_approved(settings, profile, store, publish=lambda *a: "urn:li:share:3", now=NOW)
    assert store.list_posts()[0].status == PUBLISHED


def test_publish_earliest_post_at_first(settings, profile, store):
    later, earlier = approved("later", "2026-10-10"), approved("earlier", "2026-10-11")
    later.post_at, earlier.post_at = "2026-10-11 07:30", "2026-10-11 07:00"
    store.add_post(later)
    store.add_post(earlier)
    publish_approved(settings, profile, store, publish=lambda *a: "urn:li:share:4", now=NOW)
    rows = {r.id: r for r in store.list_posts()}
    assert rows["earlier"].status == PUBLISHED
    assert rows["later"].status == APPROVED


def test_publish_explains_unreadable_post_at(settings, profile, store):
    row = approved()
    row.post_at = "tomorrow morning"
    store.add_post(row)
    publish_approved(settings, profile, store, publish=lambda *a: 1 / 0, now=NOW)
    row = store.list_posts()[0]
    assert row.status == APPROVED
    assert "Couldn't read Post at" in row.notes


def test_manual_draft_adds_another_one(settings, profile, store):
    draft_daily_post(settings, profile, store, FakeLLM(reply()), fetch=lambda _: [news()], now=NOW)
    extra = draft_daily_post(
        settings, profile, store, FakeLLM(reply("https://ex.com/b")),
        fetch=lambda _: [news("https://ex.com/b")], now=NOW, manual=True,
    )
    assert extra.id == "2026-10-11-post-080000"
    assert len(store.list_posts()) == 2


def test_daily_draft_still_runs_after_a_manual_one(settings, profile, store):
    draft_daily_post(settings, profile, store, FakeLLM(reply()), fetch=lambda _: [news()], now=NOW, manual=True)
    daily = draft_daily_post(
        settings, profile, store, FakeLLM(reply("https://ex.com/b")), fetch=lambda _: [news("https://ex.com/b")], now=NOW
    )
    assert daily.id == "2026-10-11-post"


def test_dashboard_settings_override_company_yaml(profile, tmp_path):
    from agent.daily_post import schedule_settings
    from agent.store import LocalStore

    assert schedule_settings(profile, LocalStore(tmp_path / "a.json")) == (time(10, 0), 1)
    saved = LocalStore(tmp_path / "b.json", {"default_post_time": "18:30", "max_posts_per_day": "2"})
    assert schedule_settings(profile, saved) == (time(18, 30), 2)


def test_over_limit_moves_to_tomorrow_at_default_time(settings, profile, tmp_path):
    from agent.store import LocalStore

    store = LocalStore(tmp_path / "p.json", {"default_post_time": "09:15"})
    store.add_post(approved("one", "2026-10-10"))
    store.add_post(approved("two", "2026-10-11"))
    publish_approved(settings, profile, store, publish=lambda *a: "urn:li:share:9", now=NOW)
    two = {r.id: r for r in store.list_posts()}["two"]
    assert two.status == APPROVED
    assert two.post_at == "2026-10-12 09:15"
    assert "tomorrow" in two.notes


# ---- Pictures and the company page ----


def test_every_third_post_gets_a_picture(settings, profile, store):
    rows = []
    for n in range(4):
        url = f"https://ex.com/{n}"
        llm = FakeLLM({**reply(url), "card_line": "Agentforce takes routine cases"})
        rows.append(draft_daily_post(settings, profile, store, llm, fetch=lambda _, u=url: [news(u)], now=NOW + timedelta(days=n)))
    assert [bool(r.picture) for r in rows] == [False, False, True, False]
    assert rows[2].picture == "Agentforce takes routine cases"


def test_picture_setting_from_the_sheet(settings, profile, tmp_path):
    from agent.store import LocalStore

    store = LocalStore(tmp_path / "p.json", settings={"picture_every": "1"})
    row = draft_daily_post(settings, profile, store, FakeLLM({**reply(), "card_line": "Hi"}), fetch=lambda _: [news()], now=NOW)
    assert row.picture == "Hi"
    off = LocalStore(tmp_path / "q.json", settings={"picture_every": "0"})
    assert wants_picture([], PROFILE, picture_every(profile, off)) is False


def test_company_draft_uses_company_voice_and_its_own_id(settings, profile, store):
    llm = FakeLLM(reply())
    draft_daily_post(settings, profile, store, FakeLLM(reply("https://ex.com/b")), fetch=lambda _: [news("https://ex.com/b")], now=NOW)
    row = draft_daily_post(settings, profile, store, llm, fetch=lambda _: [news()], now=NOW, account=COMPANY)
    assert row.id == "2026-10-11-company" and row.account == COMPANY
    assert 'using "we"' in llm.prompts[0][0]
    assert "company page isn't connected" in row.notes.lower()
    # The daily run doesn't add a second company draft, but the dashboard button does.
    assert draft_daily_post(settings, profile, store, FakeLLM(), fetch=lambda _: [news()], now=NOW, account=COMPANY) is None
    extra = draft_daily_post(settings, profile, store, FakeLLM(reply()), fetch=lambda _: [], now=NOW, account=COMPANY, manual=True)
    assert extra.id == "2026-10-11-company-080000"


def test_accounts_follow_the_company_page_switch(profile, tmp_path):
    from agent.store import LocalStore

    profile["content"]["company_page"] = False
    assert accounts(profile) == [PROFILE]
    profile["content"]["company_page"] = True
    assert accounts(profile) == [PROFILE, COMPANY]
    # The dashboard's setting wins.
    assert accounts(profile, LocalStore(tmp_path / "x.json", settings={"company_page": "no"})) == [PROFILE]


def test_company_post_waits_for_manual_posting_until_connected(settings, profile, store):
    row = approved("c1")
    row.account = COMPANY
    store.add_post(row)
    publish_approved(settings, profile, store, publish=lambda *a: 1 / 0, now=NOW)
    assert store.list_posts()[0].status == POST_MANUALLY


def test_company_post_uses_company_token_and_has_its_own_daily_limit(settings, profile, store):
    settings.linkedin_org_urn = "urn:li:organization:360"
    settings.linkedin_org_access_token = "org-token"
    done = approved("mine")
    done.status, done.published_at = PUBLISHED, "2026-10-11 07:00"
    store.add_post(done)
    row = approved("c1")
    row.account, row.picture, row.notes = COMPANY, "Card line", "Plan: Sunday, Point of view. Hook: X."
    store.add_post(row)
    calls = []

    def fake_publish(token, urn, text, image):
        calls.append((token, urn, image[:8] if image else None))
        return "urn:li:share:7"

    assert publish_approved(settings, profile, store, publish=fake_publish, now=NOW) == ["urn:li:share:7"]
    assert calls == [("org-token", "urn:li:organization:360", b"\x89PNG\r\n\x1a\n")]
