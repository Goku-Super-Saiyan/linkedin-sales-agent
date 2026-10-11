"""Writing rules that keep drafts from reading like AI, and a check for the worst tells.

Adapted from the humanizer and hook-formula rules in
https://github.com/sergebulaev/linkedin-skills (MIT licence, (c) 2026 Sergey Bulaev).
"""

from __future__ import annotations

import re

# Added to the system prompt for every draft.
WRITING_RULES = """\
- Open with a plain statement, ideally with a specific number or name from the article. Never open with a question.
- Do not open with "Here's what", "Here's how", "Stop X, start Y", or "In today's fast-paced world".
- No reveal bridges such as "The result?", "Plot twist:" or "The catch?". Say the point as a plain sentence.
- At most one "not X, but Y" contrast and at most one list of three in the whole post.
- Every general claim is followed within two lines by a specific: a date, a number, a product or a company name from the article.
- Avoid these words: leverage, utilize, streamline, seamless, robust, harness, unlock, foster, delve, \
navigate, landscape, ecosystem, realm, tapestry, game-changer, deep dive, empower, elevate, holistic.
- At most one em dash (—) per 100 words. Use a comma, colon or parentheses instead.
- Start sentences with the person or company doing the thing, not with an "-ing" clause.
- One or two sentences per paragraph, with a blank line between paragraphs.
- Put the question at the end, and make it specific to the reader's own work."""

# One hit is enough to ask for a rewrite.
BANNED = [
    r"\bleverag(e|es|ed|ing)\b",
    r"\butiliz(e|es|ed|ing)\b",
    r"\bstreamlin(e|es|ed|ing)\b",
    r"\bseamless(ly)?\b",
    r"\bharness(es|ed|ing)?\b",
    r"\bunlock(s|ed|ing)?\b",
    r"\bfoster(s|ed|ing)?\b",
    r"\bdelv(e|es|ed|ing)\b",
    r"\btapestry\b",
    r"\brealm\b",
    r"\bgame[- ]changer\b",
    r"\bdeep dive\b",
    r"\bin today's fast-paced\b",
    r"\blet that sink in\b",
]

REVEAL_BRIDGES = [
    r"(?im)^the (result|outcome|answer|lesson|catch|kicker|truth)\?",
    r"(?im)^(plot twist|spoiler|the twist)[:?]",
    r"(?im)^here'?s (what|how|why|the thing)\b",
    r"(?i)\bit'?s not just\b[^.,]{1,50}, it'?s\b",
]


def style_problems(text: str) -> list[str]:
    """AI-sounding patterns in a draft, in plain words. Empty list means none were found."""
    problems = []
    first_line = text.strip().split("\n", 1)[0]
    if "?" in re.split(r"(?<=[.!])\s", first_line, maxsplit=1)[0]:
        problems.append("The first sentence is a question; open with a plain statement and keep the question for the end.")

    words = sorted({m.group(0).lower() for p in BANNED for m in re.finditer(p, text, re.I)})
    if words:
        problems.append(f"Replace these AI-sounding words with plain ones: {', '.join(words)}.")

    if any(re.search(p, text) for p in REVEAL_BRIDGES):
        problems.append(
            'Remove reveal phrases like "The result?", "Here\'s how" or "It\'s not just X, it\'s Y"; '
            "state the point plainly."
        )

    dashes = text.count("—")
    allowed = max(1, len(text.split()) // 100)
    if dashes > allowed:
        problems.append(f"The post has {dashes} em dashes; use at most {allowed} and replace the rest with commas or colons.")
    return problems


def tell_count(text: str) -> int:
    """How many AI tells a draft has, to pick the cleanest one when none is perfect."""
    hits = sum(len(re.findall(p, text, re.I)) for p in BANNED)
    hits += sum(len(re.findall(p, text)) for p in REVEAL_BRIDGES)
    hits += max(0, text.count("—") - max(1, len(text.split()) // 100))
    return hits + (1 if any("question" in p for p in style_problems(text)) else 0)
