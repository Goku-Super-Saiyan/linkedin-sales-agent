from datetime import datetime, timedelta, timezone

from agent.feeds import NewsItem, parse_feed, rank

NOW = datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc)

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Salesforce Ben</title>
<item><title>Agentforce gets new CRM actions</title><link>https://ex.com/a</link>
<description>&lt;p&gt;Salesforce adds &lt;b&gt;AI agent&lt;/b&gt; actions.&lt;/p&gt;</description>
<pubDate>Sat, 10 Oct 2026 09:00:00 GMT</pubDate></item>
<item><title>No date here</title><link>https://ex.com/nodate</link></item>
</channel></rss>"""


def item(url, title="Salesforce CRM news", summary="", days_old=1):
    return NewsItem(title, url, summary, NOW - timedelta(days=days_old), "src")


def test_parse_feed_strips_html_and_skips_undated_entries():
    items = parse_feed(RSS, "https://ex.com/feed")
    assert len(items) == 1
    assert items[0].title == "Agentforce gets new CRM actions"
    assert items[0].summary == "Salesforce adds AI agent actions."
    assert items[0].source == "Salesforce Ben"


def test_rank_filters_old_used_offtopic_and_excluded():
    items = [
        item("https://ex.com/fresh"),
        item("https://ex.com/old", days_old=10),
        item("https://ex.com/used"),
        item("https://ex.com/offtopic", title="Football results"),
        item("https://ex.com/zoho", title="Salesforce vs Zoho CRM"),
        item("https://ex.com/fresh"),  # duplicate
    ]
    ranked = rank(
        items,
        keywords=["salesforce", "crm"],
        max_age_days=4,
        exclude_urls={"https://ex.com/used"},
        excluded_topics=["Zoho"],
        now=NOW,
    )
    assert [i.url for i in ranked] == ["https://ex.com/fresh"]


def test_rank_prefers_more_relevant_and_newer():
    weak = item("https://ex.com/weak", title="Salesforce update", days_old=1)
    strong = item("https://ex.com/strong", title="Salesforce Agentforce CRM automation", days_old=1)
    ranked = rank([weak, strong], ["salesforce", "agentforce", "crm", "automation"], 4, set(), [], NOW)
    assert ranked[0].url == "https://ex.com/strong"
