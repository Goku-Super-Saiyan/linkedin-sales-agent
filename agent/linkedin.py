"""Publishes a text post to her personal profile through LinkedIn's official API.

Needs the "Share on LinkedIn" product (scope w_member_social) and "Sign In with
LinkedIn using OpenID Connect" (to find her member ID) on a LinkedIn developer app.
See scripts/linkedin_auth.py for the one-time sign-in.
"""

from __future__ import annotations

import requests

UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"


class LinkedInError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status

    @property
    def needs_reauth(self) -> bool:
        return self.status == 401


def post_url(post_id: str) -> str:
    return f"https://www.linkedin.com/feed/update/{post_id}/"


def publish_text(access_token: str, person_urn: str, text: str, timeout: int = 30) -> str:
    """Publish `text` publicly. Returns the new post's ID (urn:li:share:... or urn:li:ugcPost:...)."""
    body = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    resp = requests.post(
        UGC_POSTS_URL,
        json=body,
        timeout=timeout,
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
    )
    if resp.status_code not in (200, 201):
        raise LinkedInError(
            f"LinkedIn returned {resp.status_code}: {resp.text[:300]}", status=resp.status_code
        )
    post_id = resp.headers.get("x-restli-id") or resp.json().get("id")
    if not post_id:
        raise LinkedInError("LinkedIn accepted the post but returned no ID.", status=resp.status_code)
    return post_id
