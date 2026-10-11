"""Publishes posts, with an optional picture, through LinkedIn's official API.

Her profile needs the "Share on LinkedIn" product (scope w_member_social) and "Sign In with
LinkedIn using OpenID Connect" (to find her member ID). The company page needs the Community
Management API (scope w_organization_social), signed in by a page admin.
See scripts/linkedin_auth.py for the one-time sign-in.
"""

from __future__ import annotations

import requests

UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"
REGISTER_UPLOAD_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"
UPLOAD_MECHANISM = "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"


class LinkedInError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status

    @property
    def needs_reauth(self) -> bool:
        return self.status == 401


def post_url(post_id: str) -> str:
    return f"https://www.linkedin.com/feed/update/{post_id}/"


def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "X-Restli-Protocol-Version": "2.0.0"}


def _check(resp: requests.Response, what: str) -> None:
    if resp.status_code not in (200, 201):
        raise LinkedInError(
            f"LinkedIn returned {resp.status_code} {what}: {resp.text[:300]}", status=resp.status_code
        )


def upload_image(access_token: str, author_urn: str, png: bytes, timeout: int = 30) -> str:
    """Upload a picture for `author_urn` to post. Returns its asset URN."""
    resp = requests.post(
        REGISTER_UPLOAD_URL,
        json={
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": author_urn,
                "serviceRelationships": [
                    {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
                ],
            }
        },
        timeout=timeout,
        headers=_headers(access_token),
    )
    _check(resp, "while preparing the picture upload")
    value = resp.json()["value"]
    upload_url = value["uploadMechanism"][UPLOAD_MECHANISM]["uploadUrl"]
    put = requests.put(
        upload_url,
        data=png,
        timeout=timeout,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "image/png"},
    )
    _check(put, "while uploading the picture")
    return value["asset"]


def publish(
    access_token: str, author_urn: str, text: str, image: bytes | None = None, timeout: int = 30
) -> str:
    """Publish `text` publicly as `author_urn` (a person or a company page), with an optional PNG.

    Returns the new post's ID (urn:li:share:... or urn:li:ugcPost:...).
    """
    content: dict = {"shareCommentary": {"text": text}, "shareMediaCategory": "NONE"}
    if image:
        asset = upload_image(access_token, author_urn, image, timeout=timeout)
        content["shareMediaCategory"] = "IMAGE"
        content["media"] = [{"status": "READY", "media": asset}]
    body = {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": content},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    resp = requests.post(UGC_POSTS_URL, json=body, timeout=timeout, headers=_headers(access_token))
    _check(resp, "while posting")
    post_id = resp.headers.get("x-restli-id") or resp.json().get("id")
    if not post_id:
        raise LinkedInError("LinkedIn accepted the post but returned no ID.", status=resp.status_code)
    return post_id


def publish_text(access_token: str, person_urn: str, text: str, timeout: int = 30) -> str:
    """Publish a text-only post. Kept for scripts that still call it."""
    return publish(access_token, person_urn, text, timeout=timeout)
