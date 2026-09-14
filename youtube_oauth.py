#!/usr/bin/env python3
"""One-time local login. Locks the refresh token to the Somehow True channel."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from providers.env import ROOT, load_env
from providers.youtube_upload import SCOPES, TOKEN_URI, assert_channel, expected_channel_id

ENV_PATH = ROOT / ".env"


def upsert_env(updates: dict[str, str]) -> None:
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    for key, value in updates.items():
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.M)
        line = f"{key}={value}"
        if pattern.search(text):
            text = pattern.sub(line, text)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += line + "\n"
    ENV_PATH.write_text(text, encoding="utf-8")


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Authorize the Somehow True YouTube channel")
    parser.add_argument(
        "--client-secrets",
        default="client_secret.json",
        help="Desktop OAuth client JSON downloaded from Google Cloud",
    )
    args = parser.parse_args()
    path = Path(args.client_secrets)
    if not path.exists():
        matches = sorted(ROOT.glob("client_secret*.json"))
        path = matches[0] if matches else path
    if not path.exists():
        print(f"Missing {path}. Download the Desktop OAuth client JSON from Google Cloud Credentials.")
        return 1

    wanted = expected_channel_id()
    print("A browser window will open.")
    print("1. Sign in with the Google account that manages Somehow True.")
    print("2. If Google shows a YouTube channel list, pick Somehow True, not your personal channel.")
    print(f"3. This script will refuse any channel except {wanted}.")
    print("Channel switcher if you need it: https://www.youtube.com/channel_switcher\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    if not creds.refresh_token:
        print("Google did not return a refresh token. Revoke the app and run this again.")
        return 1

    youtube = build("youtube", "v3", credentials=creds)
    try:
        channel = assert_channel(youtube)
    except RuntimeError as exc:
        print(exc)
        return 1

    secrets = json.loads(path.read_text())
    installed = secrets.get("installed") or secrets.get("web") or {}
    upsert_env({
        "YOUTUBE_CLIENT_ID": installed.get("client_id", ""),
        "YOUTUBE_CLIENT_SECRET": installed.get("client_secret", ""),
        "YOUTUBE_REFRESH_TOKEN": creds.refresh_token,
        "YOUTUBE_CHANNEL_ID": channel["id"],
    })

    print(f"Locked to {channel['title']} ({channel['id']}).")
    print("Refresh token saved to .env. Same three YouTube vars go on Railway later.")
    print("Do not commit client_secret.json or .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
