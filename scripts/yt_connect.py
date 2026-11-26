"""Connect one YouTube channel: the one-time OAuth consent, on the operator's laptop.

Opens Google's consent page for the channel (pick the Brand Account channel in
the chooser), catches the redirect on 127.0.0.1, swaps the code for a refresh
token and stores it as the GitHub secret YT_REFRESH_TOKEN_<n> through `gh`.
The token is never printed. Prints only the channel's id and title (for
accounts.yaml) and what to do next.

    YT_CLIENT_ID=... YT_CLIENT_SECRET=... python scripts/yt_connect.py 3
    # → stores YT_REFRESH_TOKEN_3 (needs `gh auth login` on this machine)
    python scripts/yt_connect.py 3 --no-gh
    # → writes the token to a 0600 file under ~/.config/ugc-factory/ for
    #   `gh secret set YT_REFRESH_TOKEN_3 < that file`; delete it afterwards

Refuses to run in GitHub Actions: a refresh token belongs in a secret, and this
script's job is to get it there without passing through a log.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)
REPO = os.environ.get("GITHUB_REPOSITORY", "nickdotname/ugc-factory")


class _Catch(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _Catch.code = (query.get("code") or [None])[0]
        _Catch.state = (query.get("state") or [None])[0]
        _Catch.error = (query.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Done. You can close this tab and go back to the terminal.\n")

    def log_message(self, *_args: object) -> None:  # silence the request log
        return


def _post(url: str, data: dict[str, str]) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        detail = json.loads(exc.read().decode() or "{}")
        raise SystemExit(f"token exchange failed: {detail.get('error')}: "
                         f"{detail.get('error_description', '')}") from None


def _channel(access_token: str) -> tuple[str, str]:
    url = CHANNELS_URL + "?" + urllib.parse.urlencode({"part": "id,snippet", "mine": "true"})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    rows = body.get("items") or []
    if not rows:
        raise SystemExit("this Google account has no YouTube channel (or the wrong one was picked)")
    return str(rows[0]["id"]), str((rows[0].get("snippet") or {}).get("title") or "")


def main() -> int:
    if os.environ.get("GITHUB_ACTIONS"):
        print("yt_connect.py is for a laptop, not CI: it needs a browser and must not log a token.",
              file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("slot", type=int, help="which YT_REFRESH_TOKEN_<n> to fill (1-16)")
    parser.add_argument("--no-gh", action="store_true",
                        help="write the token to a private file instead of `gh secret set`")
    parser.add_argument("--port", type=int, default=0, help="loopback port (default: any free)")
    args = parser.parse_args()
    if not 1 <= args.slot <= 16:
        raise SystemExit("slot must be 1-16")
    secret_name = f"YT_REFRESH_TOKEN_{args.slot}"

    client_id = os.environ.get("YT_CLIENT_ID", "")
    client_secret = os.environ.get("YT_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise SystemExit("set YT_CLIENT_ID and YT_CLIENT_SECRET in the environment first "
                         "(Cloud Console → Credentials → the Desktop app client)")

    server = http.server.HTTPServer(("127.0.0.1", args.port), _Catch)
    redirect = f"http://127.0.0.1:{server.server_port}/"
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",   # a refresh token, not just an access token
        "prompt": "consent",        # Google only issues a refresh token on a fresh consent
        "include_granted_scopes": "true",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    print(f"Opening Google's consent page. Pick the CHANNEL (Brand Account) that {secret_name} is for.")
    print("If no browser opens, paste this into one:\n  " + url)
    webbrowser.open(url)
    server.timeout = 600            # one request, or give up after ten minutes
    server.handle_request()
    server.server_close()
    if _Catch.error:
        raise SystemExit(f"Google refused: {_Catch.error}")
    if not _Catch.code or _Catch.state != state:
        raise SystemExit("no code came back (timed out, or the state did not match)")

    tokens = _post(TOKEN_URL, {
        "client_id": client_id, "client_secret": client_secret,
        "code": _Catch.code, "code_verifier": verifier,
        "grant_type": "authorization_code", "redirect_uri": redirect,
    })
    refresh = str(tokens.get("refresh_token") or "")
    if not refresh:
        raise SystemExit("Google returned no refresh token; revoke the app at myaccount.google.com/permissions "
                         "and run this again")
    channel_id, title = _channel(str(tokens.get("access_token") or ""))

    if args.no_gh:
        out = Path.home() / ".config" / "ugc-factory" / f"{secret_name.lower()}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.touch(mode=0o600)
        out.write_text(refresh)
        os.chmod(out, 0o600)
        print(f"\nToken written to {out} (mode 0600). Now, from the repo:")
        print(f"  gh secret set {secret_name} --repo {REPO} < {out} && rm {out}")
    else:
        subprocess.run(["gh", "secret", "set", secret_name, "--repo", REPO],
                       input=refresh.encode(), check=True, stdout=subprocess.DEVNULL)
        print(f"\nStored as the GitHub secret {secret_name}.")

    print(f"\nChannel: {title!r}  id: {channel_id}")
    print("accounts.yaml entry:")
    print(f"  - name: <handle>\n    network: youtube\n    provider: youtube\n"
          f"    api_key_secret: {secret_name}\n    channel_id: {channel_id}\n"
          f"    post_type: short\n    title_strategy: require")
    print("\nIf the project is not yet verified by Google, uploads are locked to private until it is "
          "(docs/brain/playbooks/add-youtube-channel.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
