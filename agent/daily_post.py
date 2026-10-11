"""Workflow 1: research news, draft posts for review, publish them once approved.

draft_daily_post  runs each morning and adds one "Pending review" row per account (her profile,
                  and the company page if it's turned on). With manual=True (the dashboard's
                  "Write a new draft") it always adds one more for the chosen account.
publish_approved  publishes rows she marked "Approved" once their "Post at" time has come.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Callable

import re

from . import feeds, images, linkedin
from .config import Settings
from .content import write_post
from .llm import LLM
from .planner import PostPlan, plan_for
from .store import (
    ACCOUNTS,
    APPROVED,
    COMPANY,
    PROFILE,
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
PILLAR_NOTE = re.compile(r"Plan: [^,]+, ([^.]+)\.")
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


def picture_every(profile: dict, store: Store) -> int:
    """Every how many posts (per account) get a picture card. 0 means never."""
    raw = store.get_settings().get("picture_every") or profile["content"].get("picture_every", 3)
    try:
        return max(0, int(raw))
    except ValueError:
        log.warning("Ignoring picture_every %r; expected a number.", raw)
        return int(profile["content"].get("picture_every", 3))


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


def wants_picture(posts: list[PostRow], account: str, every: int) -> bool:
    """True when the last every-1 posts for this account had no picture."""
    if every <= 0:
        return False
    mine = [p for p in posts if p.account == account]
    since = 0
    for p in reversed(mine):
        if p.picture.strip():
            break
        since += 1
    return since >= every - 1


def _connected(settings: Settings, account: str) -> tuple[str | None, str | None, object]:
    """Token, author URN and token expiry for an account; the first two are None if not connected."""
    if account == COMPANY:
        if not settings.company_configured:
            return None, None, None
        return settings.linkedin_org_access_token, settings.linkedin_org_urn, settings.linkedin_org_token_expires_on
    if not settings.linkedin_configured:
        return None, None, None
    return settings.linkedin_access_token, settings.linkedin_person_urn, settings.linkedin_token_expires_on


def _notes(settings: Settings, plan: PostPlan, evergreen: bool, today: datetime, account: str = PROFILE) -> str:
    notes = []
    if evergreen and plan.news_day:
        notes.append("No fresh Salesforce/AI news found, so this is an evergreen topic.")
    token, _, expires = _connected(settings, account)
    if not token:
        where = "the company page" if account == COMPANY else "LinkedIn"
        notes.append(f"{where[0].upper()}{where[1:]} isn't connected yet: once you approve, copy the text "
                     "(and download the picture, if there is one) and post it yourself.")
    if token and expires and expires - today.date() <= timedelta(
        days=TOKEN_WARNING_DAYS
    ):
        notes.append(f"LinkedIn sign-in expires on {expires:%d %b}. Ask Goku to renew it.")
    return " ".join(notes)


def accounts(profile: dict, store: Store | None = None) -> list[str]:
    """Accounts that get a daily draft: her profile, plus the company page when it's turned on.

    The dashboard's Settings panel (company_page = yes/no) wins over company.yaml.
    """
    saved = (store.get_settings() if store else {}).get("company_page", "").strip().lower()
    on = saved == "yes" if saved in ("yes", "no") else bool(profile["content"].get("company_page"))
    return [PROFILE, COMPANY] if on else [PROFILE]


def draft_daily_post(
    settings: Settings,
    profile: dict,
    store: Store,
    llm: LLM,
    fetch: Callable[[list[str]], list[feeds.NewsItem]] = feeds.collect,
    now: datetime | None = None,
    manual: bool = False,
    account: str = PROFILE,
) -> PostRow | None:
    """Add one draft for `account`. The daily run skips it if today's draft for that account exists."""
    if account not in ACCOUNTS:
        raise ValueError(f"Unknown account {account!r}; use one of {ACCOUNTS}.")
    now = now or settings.now()
    today = now.date().isoformat()
    posts = store.list_posts()
    prefix = f"{today}-company" if account == COMPANY else f"{today}-post"
    if not manual and any(p.id == prefix for p in posts):
        log.info("Today's draft %s already exists; nothing to do.", prefix)
        return None

    content = profile["content"]
    mine = [p for p in posts if p.account == account]
    plan = plan_for(profile, mine, now)
    log.info("Plan for today (%s): %s", account, plan.note())
    items = [] if not plan.use_news else feeds.rank(
        fetch(content["feeds"]),
        keywords=content["keywords"],
        max_age_days=content["max_age_days"],
        exclude_urls=_used_urls(posts),
        excluded_topics=profile["company"]["excluded_topics"],
        now=now,
    )
    log.info("Found %d usable news items.", len(items))
    if not items:
        plan.use_news = False
    draft = write_post(llm, profile, items, plan=plan, for_company=account == COMPANY)
    picture = ""
    if wants_picture(posts, account, picture_every(profile, store)):
        picture = draft.card_line or draft.topic

    row = PostRow(
        id=f"{prefix}-{now:%H%M%S}" if manual else prefix,
        date=today,
        status=PENDING,
        topic=draft.topic,
        text=draft.post,
        sources="\n".join(draft.source_urls),
        notes=" ".join(
            filter(None, [plan.note(), _notes(settings, plan, draft.evergreen, now, account), *draft.style_warnings])
        ),
        account=account,
        picture=picture,
    )
    store.add_post(row)
    log.info("Saved draft %s for review: %s", row.id, row.topic)
    return row


def picture_for(post: PostRow, profile: dict) -> bytes | None:
    """The PNG card for a post, or None if it has no picture."""
    if not post.picture.strip():
        return None
    match = PILLAR_NOTE.search(post.notes)
    return images.render_card(post.picture, match.group(1) if match else "", profile.get("brand"))


def publish_approved(
    settings: Settings,
    profile: dict,
    store: Store,
    publish: Callable[..., str] = linkedin.publish,
    now: datetime | None = None,
) -> list[str]:
    """Publish approved rows, oldest first, within each account's daily limit. Returns post IDs."""
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

    default_time, limit = schedule_settings(profile, store)
    published: list[str] = []
    done_today = {
        account: sum(1 for p in posts if p.account == account and p.is_status(PUBLISHED) and p.published_at.startswith(today))
        for account in ACCOUNTS
    }
    for p in approved:
        token, author, _ = _connected(settings, p.account)
        if not token:
            where = "The company page" if p.for_company else "LinkedIn"
            store.update_post(
                p.id,
                status=POST_MANUALLY,
                notes=f"{where} isn't connected yet. Copy the post text (and download the picture, if "
                "there is one), publish it on LinkedIn, and paste the link in the LinkedIn link column.",
            )
            continue
        if done_today.get(p.account, 0) >= limit:
            # Move it to tomorrow, or it would go out just after midnight.
            tomorrow = datetime.combine(now.date() + timedelta(days=1), default_time or now.time())
            store.update_post(
                p.id,
                post_at=tomorrow.strftime("%Y-%m-%d %H:%M"),
                notes=f"Today's limit of {limit} post(s) for {p.account.lower()} was reached, "
                "so this moved to tomorrow.",
            )
            continue
        if not p.text.strip():
            store.update_post(p.id, status=FAILED, notes="The post text is empty.")
            continue
        # Mark first so a crash mid-publish can never cause a second, duplicate post.
        store.update_post(p.id, status=PUBLISHING, notes="")
        try:
            post_id = publish(token, author, p.text, picture_for(p, profile))
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
        done_today[p.account] = done_today.get(p.account, 0) + 1
        published.append(post_id)
        log.info("Published %s as %s", p.id, post_id)
    return published
