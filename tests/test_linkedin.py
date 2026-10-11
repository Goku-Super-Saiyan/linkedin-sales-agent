import pytest

from agent import linkedin


class Resp:
    def __init__(self, status, headers=None, body=None, text=""):
        self.status_code = status
        self.headers = headers or {}
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


def test_publish_sends_public_text_post(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout, headers):
        sent.update(url=url, json=json, headers=headers)
        return Resp(201, headers={"x-restli-id": "urn:li:share:42"})

    monkeypatch.setattr(linkedin.requests, "post", fake_post)
    post_id = linkedin.publish_text("tok", "urn:li:person:abc", "Hello")
    assert post_id == "urn:li:share:42"
    assert sent["url"] == linkedin.UGC_POSTS_URL
    assert sent["headers"]["Authorization"] == "Bearer tok"
    assert sent["json"]["author"] == "urn:li:person:abc"
    share = sent["json"]["specificContent"]["com.linkedin.ugc.ShareContent"]
    assert share["shareCommentary"]["text"] == "Hello"
    assert sent["json"]["visibility"]["com.linkedin.ugc.MemberNetworkVisibility"] == "PUBLIC"


def test_publish_raises_with_status(monkeypatch):
    monkeypatch.setattr(linkedin.requests, "post", lambda *a, **k: Resp(401, text="expired"))
    with pytest.raises(linkedin.LinkedInError) as err:
        linkedin.publish_text("tok", "urn:li:person:abc", "Hello")
    assert err.value.needs_reauth


def test_publish_with_picture_uploads_it_first(monkeypatch):
    calls = []

    def fake_post(url, json, timeout, headers):
        calls.append(("post", url, json))
        if url == linkedin.REGISTER_UPLOAD_URL:
            mech = {linkedin.UPLOAD_MECHANISM: {"uploadUrl": "https://upload.example/x"}}
            return Resp(200, body={"value": {"uploadMechanism": mech, "asset": "urn:li:digitalmediaAsset:9"}})
        return Resp(201, headers={"x-restli-id": "urn:li:share:43"})

    def fake_put(url, data, timeout, headers):
        calls.append(("put", url, data))
        return Resp(201)

    monkeypatch.setattr(linkedin.requests, "post", fake_post)
    monkeypatch.setattr(linkedin.requests, "put", fake_put)
    assert linkedin.publish("tok", "urn:li:organization:360", "Hi", image=b"PNG") == "urn:li:share:43"
    register, put, post = calls
    assert register[2]["registerUploadRequest"]["owner"] == "urn:li:organization:360"
    assert put[1:] == ("https://upload.example/x", b"PNG")
    share = post[2]["specificContent"]["com.linkedin.ugc.ShareContent"]
    assert share["shareMediaCategory"] == "IMAGE"
    assert share["media"] == [{"status": "READY", "media": "urn:li:digitalmediaAsset:9"}]
    assert post[2]["author"] == "urn:li:organization:360"
