"""Writing rules that keep drafts from reading like AI, an editing checklist, and a check for the worst tells.

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

# The editing pass goes through this list once for every draft.
AUDIT_CHECKLIST = """\
- Line 1 carries the strongest point. The first 210 characters make a reader want to click "see more". No throat-clearing.
- Every general claim is backed within two lines by a specific from the draft: a number, a date, a product or a company.
- No staccato stacks ("Short. Punchy. Done.", "No X. No Y. Just Z."), no one-word paragraphs, at most 2 sentence fragments in the post.
- No mechanical long-short-long-short sentence rhythm, and no paragraph where every sentence is the same length.
- No announcements of honesty ("Let me be honest", "Real talk", "Unpopular opinion") and no hedges like "I might be wrong, but".
- No "I'm excited to share" style openers. Say the thing.
- At most one contrast and one list of three. A list of three must be three concrete items, never three adjectives.
- Ends with a specific question about the reader's own work, never "What do you think?", "Thoughts?" or "Agree or disagree?".
- No links in the post body.
- Keeps contractions, plain words and the writer's opinions. A uniformly flat, neutral tone also reads as AI."""

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
    r"(?im)^(let me be (honest|real|direct|clear)|real talk|unpopular opinion|full transparency)\b",
    r"(?im)^i'?m (so )?(excited|thrilled|delighted) to (share|announce)\b",
    r"(?i)\bno \w+\. no \w+\. (just|only) \w+",
    r"(?m)^\w+\.$",
]

DEAD_CLOSERS = [
    r"(?i)what do you think\?",
    r"(?i)\bthoughts\?",
    r"(?i)agree or disagree\?",
    r"(?i)let me know in the comments",
    r"(?i)tag someone who",
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
            'Remove reveal and performance phrases like "The result?", "Here\'s how", "It\'s not just X, '
            'it\'s Y", "Let me be honest", "No X. No Y. Just Z." or one-word paragraphs; state the point plainly.'
        )

    if any(re.search(p, text) for p in DEAD_CLOSERS):
        problems.append('End with a specific question about the reader\'s own work, not "What do you think?" or "Thoughts?".')

    dashes = text.count("—")
    allowed = max(1, len(text.split()) // 100)
    if dashes > allowed:
        problems.append(f"The post has {dashes} em dashes; use at most {allowed} and replace the rest with commas or colons.")
    return problems


def tell_count(text: str) -> int:
    """How many AI tells a draft has, to pick the cleanest one when none is perfect."""
    hits = sum(len(re.findall(p, text, re.I)) for p in BANNED)
    hits += sum(len(re.findall(p, text)) for p in REVEAL_BRIDGES + DEAD_CLOSERS)
    hits += max(0, text.count("—") - max(1, len(text.split()) // 100))
    return hits + (1 if any("question" in p for p in style_problems(text)) else 0)
