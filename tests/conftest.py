import pytest

from agent.config import Settings, load_profile
from agent.store import LocalStore


class FakeLLM:
    """Returns queued replies in order and records every prompt it was sent."""

    name = "fake"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.audit_replies = []
        self.prompts = []

    def generate_json(self, system, prompt, schema):
        self.prompts.append((system, prompt))
        if "changes" in schema["properties"]:
            # The audit pass: hand back a queued edit, or the draft unchanged.
            if self.audit_replies:
                return self.audit_replies.pop(0)
            return {"post": prompt.split("<draft>\n", 1)[1].rsplit("\n</draft>", 1)[0], "changes": []}
        return self.replies.pop(0)


@pytest.fixture
def profile():
    return load_profile()


@pytest.fixture
def store(tmp_path):
    return LocalStore(tmp_path / "posts.json")


@pytest.fixture
def settings():
    return Settings(
        linkedin_access_token="token",
        linkedin_person_urn="urn:li:person:abc",
    )


def good_post(extra=""):
    return (
        "Salesforce just announced new Agentforce actions for service teams. "
        "For mid-sized companies this means routine case updates can be handled by an agent "
        "while people focus on the conversations that need judgment. The practical first step "
        "is to list the five most repeated tasks your team does in Salesforce each week. "
        f"{extra}How is your team deciding what to automate first?\n\n#Salesforce #AI #CRM"
    )
