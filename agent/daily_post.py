"""Workflow 1: research news, draft a post for review, publish it once approved.

draft_daily_post  runs each morning and adds one "Pending review" row to the sheet. With
                  manual=True (the dashboard's "Write a new draft") it always adds one more.
publish_approved  publishes rows she marked "Approved" once their "Post at" time has come.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Callable

from . import feeds, linkedin
from .config import Settings
from .content import write_post
from .llm import LLM
from .store import (
    APPROVED,
    FAILED,
    POST_MANUALLY,
    PENDING,
    PUBLISHED,
    PUBLISHING,
    PostRow,
    Store,
)

log = logging.getLogger(__name__)

TOKEN_WARNING_DAYS = 7
POST_AT_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def parse_post_at(value: str, now: datetime) -> datetime | None:
    """Read a "Post at" cell in the schedule's timezone. Empty means now; bad input raises ValueError."""
    value = value.strip()
    if not value:
        return None
    for fmt in POST_AT_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=now.tzinfo)
        except ValueError:
            continue
    raise ValueError(value)


def schedule_settings(profile: dict, store: Store) -> tuple[time | None, int]:
    """Default post time and daily limit: the dashboard's Settings tab wins over company.yaml."""
    schedule = profile["schedule"]
    saved = store.get_settings()
    raw_time = saved.get("default_post_time", schedule.get("default_post_time") or "").strip()
    try:
        default_time = datetime.strptime(raw_time, "%H:%M").time() if raw_time else None
    except ValueError:
        log.warning("Ignoring default post time %r; expected HH:MM.", raw_time)
        default_time = None
    try:
        limit = max(1, int(saved.get("max_posts_per_day") or schedule["max_posts_per_day"]))
    except ValueError:
        limit = schedule["max_posts_per_day"]
    return default_time, limit


def _used_urls(posts: list[PostRow]) -> set[str]:
    urls = set()
    for p in posts:
        urls.update(u.strip() for u in p.sources.splitlines() if u.strip())
    return urls


def _evergreen_topic(profile: dict, posts: list[PostRow], today: datetime) -> str:
    topics = profile["content"]["evergreen_topics"]
    used = {p.topic for p in posts}
    unused = [t for t in topics if t not in used]
    pool = unused or topics
    return pool[today.toordinal() % len(pool)]


def _notes(settings: Settings, evergreen: bool, today: datetime) -> str:
    notes = []
    if evergreen:
        notes.append("No fresh Salesforce/AI news found, so this is an evergreen topic.")
    if not settings.linkedin_configured:
        notes.append("LinkedIn isn't connected yet: once you approve, copy the text and post it yourself.")
    expires = settings.linkedin_token_expires_on
    if settings.linkedin_configured and expires and expires - today.date() <= timedelta(
        days=TOKEN_WARNING_DAYS
    ):
        notes.append(f"LinkedIn sign-in expires on {expires:%d %b}. Ask Goku to renew it.")
    return " ".join(notes)


def draft_daily_post(
    settings: Settings,
    profile: dict,
    store: Store,
    llm: LLM,
    fetch: Callable[[list[str]], list[feeds.NewsItem]] = feeds.collect,
    now: datetime | None = None,
    manual: bool = False,
) -> PostRow | None:
    now = now or settings.now()
    today = now.date().isoformat()
    posts = store.list_posts()
    daily_id = f"{today}-post"
    if not manual and any(p.id == daily_id for p in posts):
        log.info("Today's draft %s already exists; nothing to do.", daily_id)
        return None

    content = profile["content"]
    items = feeds.rank(
        fetch(content["feeds"]),
        keywords=content["keywords"],
        max_age_days=content["max_age_days"],
        exclude_urls=_used_urls(posts),
        excluded_topics=profile["company"]["excluded_topics"],
        now=now,
    )
    log.info("Found %d usable news items.", len(items))
    draft = write_post(llm, profile, items, evergreen_topic=_evergreen_topic(profile, posts, now))

    row = PostRow(
        id=f"{today}-post-{now:%H%M%S}" if manual else daily_id,
        date=today,
        status=PENDING,
        topic=draft.topic,
        text=draft.post,
        sources="\n".join(draft.source_urls),
        notes=_notes(settings, draft.evergreen, now),
    )
    store.add_post(row)
    log.info("Saved draft %s for review: %s", row.id, row.topic)
    return row


def publish_approved(
    settings: Settings,
    profile: dict,
    store: Store,
    publish: Callable[[str, str, str], str] = linkedin.publish_text,
    now: datetime | None = None,
) -> list[str]:
    """Publish approved rows, oldest first, within the daily limit. Returns published post IDs."""
    now = now or settings.now()
    today = now.date().isoformat()
    posts = store.list_posts()
    approved = []
    for p in posts:
        if not p.is_status(APPROVED):
            continue
        try:
            post_at = parse_post_at(p.post_at, now)
        except ValueError:
            store.update_post(
                p.id, notes=f'Couldn\'t read Post at "{p.post_at}". Use the format 2026-10-12 10:30.'
            )
            continue
        if post_at and post_at > now:
            log.info("%s is scheduled for %s.", p.id, p.post_at)
            continue
        approved.append((post_at or now, p))
    approved = [p for _, p in sorted(approved, key=lambda pair: (pair[0], pair[1].date))]
    if not approved:
        log.info("Nothing approved and due to publish.")
        return []

    if not settings.linkedin_configured:
        for p in approved:
            store.update_post(
                p.id,
                status=POST_MANUALLY,
                notes="LinkedIn isn't connected yet. Copy the post text, publish it on LinkedIn, "
                "and paste the link in the LinkedIn link column.",
            )
        return []

    default_time, limit = schedule_settings(profile, store)
    already = sum(1 for p in posts if p.is_status(PUBLISHED) and p.published_at.startswith(today))
    published: list[str] = []
    for p in approved:
        if already + len(published) >= limit:
            # Move it to tomorrow, or it would go out just after midnight.
            tomorrow = datetime.combine(now.date() + timedelta(days=1), default_time or now.time())
            store.update_post(
                p.id,
                post_at=tomorrow.strftime("%Y-%m-%d %H:%M"),
                notes=f"Today's limit of {limit} post(s) was reached, so this moved to tomorrow.",
            )
            continue
        if not p.text.strip():
            store.update_post(p.id, status=FAILED, notes="The post text is empty.")
            continue
        # Mark first so a crash mid-publish can never cause a second, duplicate post.
        store.update_post(p.id, status=PUBLISHING, notes="")
        try:
            post_id = publish(settings.linkedin_access_token, settings.linkedin_person_urn, p.text)
        except linkedin.LinkedInError as exc:
            note = (
                "LinkedIn sign-in has expired. Ask Goku to renew it, then set Status back to Approved."
                if exc.needs_reauth
                else f"LinkedIn rejected the post: {exc}. Fix it and set Status back to Approved."
            )
            store.update_post(p.id, status=FAILED, notes=note)
            log.error("Publishing %s failed: %s", p.id, exc)
            continue
        store.update_post(
            p.id,
            status=PUBLISHED,
            linkedin_link=linkedin.post_url(post_id),
            published_at=now.strftime("%Y-%m-%d %H:%M"),
        )
        published.append(post_id)
        log.info("Published %s as %s", p.id, post_id)
    return published
