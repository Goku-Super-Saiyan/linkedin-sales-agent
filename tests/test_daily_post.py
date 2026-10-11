from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from agent import linkedin
from agent.daily_post import draft_daily_post, publish_approved
from agent.feeds import NewsItem
from agent.store import (
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

    def fake_publish(token, urn, text):
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
