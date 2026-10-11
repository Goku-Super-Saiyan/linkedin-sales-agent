"""Collects recent Salesforce / AI news from RSS feeds and ranks it by relevance."""

from __future__ import annotations

import calendar
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser
import requests

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; linkedin-sales-agent/1.0)"
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class NewsItem:
    title: str
    url: str
    summary: str
    published: datetime
    source: str
    score: float = 0.0


def _clean(text: str, limit: int = 600) -> str:
    text = html.unescape(_TAG_RE.sub(" ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _published(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return None


def parse_feed(content: bytes | str, source: str) -> list[NewsItem]:
    parsed = feedparser.parse(content)
    items = []
    for entry in parsed.entries:
        published = _published(entry)
        url = entry.get("link")
        title = _clean(entry.get("title", ""), 200)
        if not (published and url and title):
            continue
        items.append(
            NewsItem(
                title=title,
                url=url,
                summary=_clean(entry.get("summary", "")),
                published=published,
                source=parsed.feed.get("title") or source,
            )
        )
    return items


def fetch_feed(url: str, timeout: int = 20) -> list[NewsItem]:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return parse_feed(resp.content, url)


def score(item: NewsItem, keywords: list[str], now: datetime) -> float:
    text = f"{item.title} {item.summary}".lower()
    hits = sum(1 for k in keywords if k.lower() in text)
    title_hits = sum(1 for k in keywords if k.lower() in item.title.lower())
    age_days = (now - item.published).total_seconds() / 86400
    return hits + 2 * title_hits - 0.5 * age_days


def rank(
    items: list[NewsItem],
    keywords: list[str],
    max_age_days: int,
    exclude_urls: set[str],
    excluded_topics: list[str],
    now: datetime | None = None,
    limit: int = 8,
) -> list[NewsItem]:
    """Fresh, unused, on-topic items, best first. Items with no keyword match are dropped."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)
    seen: set[str] = set()
    ranked = []
    for item in items:
        if item.published < cutoff or item.url in exclude_urls or item.url in seen:
            continue
        text = f"{item.title} {item.summary}".lower()
        if any(t.lower() in text for t in excluded_topics):
            continue
        if not any(k.lower() in text for k in keywords):
            continue
        seen.add(item.url)
        item.score = score(item, keywords, now)
        ranked.append(item)
    ranked.sort(key=lambda i: i.score, reverse=True)
    return ranked[:limit]


def collect(feed_urls: list[str]) -> list[NewsItem]:
    """Fetch every feed; a broken feed is logged and skipped, never fatal."""
    items: list[NewsItem] = []
    for url in feed_urls:
        try:
            items.extend(fetch_feed(url))
        except Exception as exc:  # noqa: BLE001 - one bad feed must not stop the run
            log.warning("Skipping feed %s: %s", url, exc)
    return items
