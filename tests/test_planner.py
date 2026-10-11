from datetime import datetime
from zoneinfo import ZoneInfo

from agent.planner import HOOKS, plan_for
from agent.store import PENDING, PostRow

IST = ZoneInfo("Asia/Kolkata")
MONDAY = datetime(2026, 10, 12, 8, 0, tzinfo=IST)
THURSDAY = datetime(2026, 10, 15, 8, 0, tzinfo=IST)


def test_every_planned_hook_exists(profile):
    for day in profile["content"]["weekly_plan"].values():
        assert set(day["hooks"]) <= set(HOOKS)


def test_monday_is_news_with_number_first(profile):
    plan = plan_for(profile, [], MONDAY)
    assert plan.use_news and plan.news_day
    assert plan.hook == "number_first"
    assert plan.note() == "Plan: Monday, Industry news. Hook: Number first."


def test_hook_used_this_week_is_skipped(profile):
    notes = "Plan: Friday, Point of view. Hook: Number first."
    earlier = PostRow("p", "2026-10-09", PENDING, "t", "x", notes=notes)
    assert plan_for(profile, [earlier], MONDAY).hook == "contrarian"


def test_hook_from_last_week_is_allowed_again(profile):
    notes = "Plan: Monday, Industry news. Hook: Number first."
    old = PostRow("p", "2026-10-05", PENDING, "t", "x", notes=notes)
    assert plan_for(profile, [old], MONDAY).hook == "number_first"


def test_evergreen_day_uses_its_own_topics_and_moves_on_for_extra_drafts(profile):
    first = plan_for(profile, [], THURSDAY)
    assert not first.use_news
    assert first.topic in profile["content"]["weekly_plan"]["thursday"]["topics"]
    extra = plan_for(profile, [PostRow("p", "2026-10-15", PENDING, "t", "x")], THURSDAY)
    assert extra.topic != first.topic


def test_missing_plan_falls_back_to_news(profile):
    del profile["content"]["weekly_plan"]
    plan = plan_for(profile, [], MONDAY)
    assert plan.use_news and plan.hook == "number_first" and plan.pillar == "Industry news"
