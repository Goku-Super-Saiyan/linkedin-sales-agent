"""One-time LinkedIn sign-in. Run on a computer with a browser:

    LINKEDIN_CLIENT_ID=... LINKEDIN_CLIENT_SECRET=... python scripts/linkedin_auth.py

She signs in to LinkedIn in the browser window that opens and clicks Allow. The script
prints the three values to save as GitHub secrets. The sign-in lasts about 60 days;
run this again before it expires.

The developer app must have the redirect URL http://localhost:8765/callback and the
products "Share on LinkedIn" and "Sign In with LinkedIn using OpenID Connect".
"""

from __future__ import annotations

import http.server
import os
import secrets
import sys
import urllib.parse
import webbrowser
from datetime import date, timedelta

import requests

REDIRECT_URI = "http://localhost:8765/callback"
SCOPES = "openid profile w_member_social"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"


def wait_for_code(expected_state: str) -> str:
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - name required by BaseHTTPRequestHandler
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h2>Done. You can close this window.</h2>")

        def log_message(self, *args):
            pass

    with http.server.HTTPServer(("localhost", 8765), Handler) as server:
        while "code" not in result and "error" not in result:
            server.handle_request()

    if "error" in result:
        sys.exit(f"LinkedIn sign-in failed: {result.get('error_description', result['error'])}")
    if result.get("state") != expected_state:
        sys.exit("Sign-in response did not match this request; please run the script again.")
    return result["code"]


def main() -> None:
    client_id = os.environ.get("LINKEDIN_CLIENT_ID")
    client_secret = os.environ.get("LINKEDIN_CLIENT_SECRET")
    if not (client_id and client_secret):
        sys.exit("Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET first.")

    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
        }
    )
    print("Opening LinkedIn sign-in. If no browser opens, visit:\n", url)
    webbrowser.open(url)
    code = wait_for_code(state)

    token = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    token.raise_for_status()
    token_data = token.json()
    access_token = token_data["access_token"]
    expires_on = date.today() + timedelta(seconds=int(token_data.get("expires_in", 0)))

    me = requests.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    me.raise_for_status()
    person_urn = f"urn:li:person:{me.json()['sub']}"

    print(f"\nSigned in as {me.json().get('name', 'unknown')}.")
    print("Save these as GitHub repository secrets:\n")
    print(f"LINKEDIN_ACCESS_TOKEN = {access_token}")
    print(f"LINKEDIN_PERSON_URN = {person_urn}")
    print(f"LINKEDIN_TOKEN_EXPIRES_ON = {expires_on.isoformat()}")


if __name__ == "__main__":
    main()
