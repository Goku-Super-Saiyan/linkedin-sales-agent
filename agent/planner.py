"""The weekly content plan: which kind of post each day gets, and which hook shape it uses.

Pillars, hook shapes and the no-repeat rule are adapted from the content-planner and
hook-formula references in https://github.com/sergebulaev/linkedin-skills (MIT licence,
(c) 2026 Sergey Bulaev). Only shapes that work without personal stories or invented
numbers are used, because posts may only state facts from the source articles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .store import PostRow

# Hook shapes the plan can pick from: (name shown in the sheet, how to write it).
HOOKS = {
    "number_first": (
        "Number first",
        "Open with the most specific number, date or name from the article, stated plainly in the "
        "first line. Then say what it means for the reader's business, then one practical step they "
        "can take this week.",
    ),
    "contrarian": (
        "Contrarian take",
        "Open with one clear statement that goes against what most people assume about this topic. "
        "Back it with facts from the article (for an evergreen topic, with plain reasoning and no "
        "numbers). Say who it applies to and who it doesn't.",
    ),
    "false_binary": (
        "Two answers, then a third",
        "Name the two answers most teams reach for on this problem and give one line on why each "
        "falls short. Name the shared flaw, then the better third option in 2-3 concrete lines. "
        "Close by asking which one the reader uses today. The two options must be ones readers "
        "really choose, not strawmen.",
    ),
    "diverging_paths": (
        "Two paths over time",
        "Describe two approaches that look similar today, then show how they drift apart over time "
        "(for example: month one, month six). End with one short line that sums up the difference. "
        "This is the post's only contrast.",
    ),
    "explain_simply": (
        "Explained simply",
        'Open with a statement like "<term>, explained simply." Then break the term into its parts, '
        "one short line each, in plain words a non-technical CEO would follow. Then one line on why "
        "it matters to a 50-500 person company. Keep every explanation correct.",
    ),
    "checklist": (
        "Checklist",
        "Open with the problem the checklist prevents, in one plain line. Then a numbered list of "
        "5 to 7 steps, each one line with a specific action. Do not claim prices, clients or "
        "results. Close with a question about which step the reader skips most.",
    ),
}

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
# How far back to look so a hook shape isn't reused in the same week.
NO_REPEAT_DAYS = 6
HOOK_NOTE = re.compile(r"Hook: ([^.]+)\.")


@dataclass
class PostPlan:
    weekday: str
    pillar: str
    use_news: bool
    hook: str
    topic: str  # Evergreen topic, used when there's no news or the day doesn't use news.
    news_day: bool = False  # The plan wanted news; stays True when no news turned up.

    @property
    def hook_name(self) -> str:
        return HOOKS[self.hook][0]

    @property
    def hook_guide(self) -> str:
        return HOOKS[self.hook][1]

    def note(self) -> str:
        return f"Plan: {self.weekday.title()}, {self.pillar}. Hook: {self.hook_name}."


def _recent_hooks(posts: list[PostRow], now: datetime) -> set[str]:
    since = (now - timedelta(days=NO_REPEAT_DAYS)).date().isoformat()
    names = set()
    for p in posts:
        if p.date >= since:
            names.update(m.strip() for m in HOOK_NOTE.findall(p.notes))
    return names


def plan_for(profile: dict, posts: list[PostRow], now: datetime) -> PostPlan:
    """Today's plan from content.weekly_plan, with a hook shape not used in the last few days."""
    content = profile["content"]
    weekday = WEEKDAYS[now.weekday()]
    day = (content.get("weekly_plan") or {}).get(weekday) or {}
    hooks = [h for h in day.get("hooks") or ["number_first"] if h in HOOKS] or ["number_first"]

    used = _recent_hooks(posts, now)
    hook = next((h for h in hooks if HOOKS[h][0] not in used), hooks[0])

    topics = day.get("topics") or content["evergreen_topics"]
    # Rotate weekly, and give each extra draft on the same day the next topic.
    drafted_today = sum(1 for p in posts if p.date == now.date().isoformat())
    topic = topics[(now.toordinal() // 7 + drafted_today) % len(topics)]

    use_news = day.get("source", "news") == "news"
    return PostPlan(
        weekday=weekday,
        pillar=day.get("pillar", "Industry news"),
        use_news=use_news,
        hook=hook,
        topic=topic,
        news_day=use_news,
    )
