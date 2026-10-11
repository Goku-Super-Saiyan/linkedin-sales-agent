from agent.style import style_problems
from conftest import good_post


def test_clean_post_has_no_problems():
    assert style_problems(good_post()) == []


def test_question_opener():
    assert any("question" in p for p in style_problems("Is your CRM slowing you down? " + good_post()))


def test_banned_words_listed_once():
    problems = style_problems(good_post("We leverage data. Leveraging it helps. "))
    assert problems == ["Replace these AI-sounding words with plain ones: leverage, leveraging."]


def test_reveal_bridge():
    assert style_problems(good_post("\n\nThe result? Faster cases. "))
    assert style_problems(good_post("It's not just a tool, it's a teammate. "))


def test_em_dash_density():
    assert style_problems(good_post("One — two. ")) == []
    assert any("em dashes" in p for p in style_problems(good_post("One — two — three. ")))
