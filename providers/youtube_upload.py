"""YouTube Data API upload. Always private with AI/synthetic disclosure."""
from __future__ import annotations

import os
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from providers.env import load_env

load_env()

SCOPES = ["https://www.googleapis.com/auth/youtube"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_CHANNEL_ID = "UCZqmUx29Va8Zud78Fj_0Geg"


YOUTUBE_TITLE_LIMIT = 100
YOUTUBE_URL_RE = re.compile(
    r"https://(?:studio\.youtube\.com/video/([A-Za-z0-9_-]+)/edit"
    r"|youtu\.be/([A-Za-z0-9_-]+)"
    r"|(?:www\.)?youtube\.com/watch\?v=([A-Za-z0-9_-]+))"
)


def youtube_links(url: str = "", video_id: str = "") -> dict:
    """Studio + watch URLs from a video id or any YouTube URL we print."""
    found = (video_id or "").strip()
    match = YOUTUBE_URL_RE.search(url or "")
    if match:
        found = next((group for group in match.groups() if group), found)
    if not found and "/video/" in (url or ""):
        found = url.split("/video/", 1)[1].split("/", 1)[0]
    if not found:
        return {"video_id": "", "studio": (url or "").strip(), "watch": "", "url": (url or "").strip()}
    studio = f"https://studio.youtube.com/video/{found}/edit"
    watch = f"https://youtu.be/{found}"
    return {"video_id": found, "studio": studio, "watch": watch, "url": studio}


def extract_youtube_url(text: str) -> str:
    match = YOUTUBE_URL_RE.search(text or "")
    return match.group(0) if match else ""


def youtube_title(text: str, limit: int = YOUTUBE_TITLE_LIMIT) -> str:
    """Complete title that fits YouTube. Never mid-word, never ellipsis."""
    title = re.sub(r"\s+", " ", text or "").strip().rstrip(".")
    if len(title) <= limit:
        return title
    tightened = title
    for fluff in ("this year, ", "this year ", "In fact, ", "actually "):
        tightened = tightened.replace(fluff, "")
    tightened = re.sub(r"\s+", " ", tightened).strip()
    if len(tightened) <= limit:
        return tightened
    if ", " in tightened:
        after = tightened.split(", ", 1)[1].strip()
        if after:
            after = after[0].upper() + after[1:]
            if len(after) <= limit:
                return after
    for sep in (". ", "! ", "? ", "; ", " — ", " - "):
        first = tightened.split(sep)[0].strip()
        if 24 <= len(first) <= limit:
            return first
    words = tightened.split()
    kept: list[str] = []
    for word in words:
        trial = " ".join(kept + [word])
        if len(trial) > limit:
            break
        kept.append(word)
    weak = {"a", "an", "the", "from", "to", "of", "in", "on", "and", "or", "for", "one", "full"}
    while kept and kept[-1].lower().strip(".,;:") in weak:
        kept.pop()
    return " ".join(kept) if kept else tightened[:limit]


def expected_channel_id() -> str:
    return os.environ.get("YOUTUBE_CHANNEL_ID", DEFAULT_CHANNEL_ID).strip() or DEFAULT_CHANNEL_ID


def authorized_channel(youtube=None) -> dict:
    youtube = youtube or build("youtube", "v3", credentials=_credentials())
    data = youtube.channels().list(part="id,snippet", mine=True).execute()
    items = data.get("items") or []
    if not items:
        raise RuntimeError("OAuth worked but no YouTube channel is attached to this login.")
    channel = items[0]
    return {
        "id": channel["id"],
        "title": channel.get("snippet", {}).get("title", ""),
    }


def assert_channel(youtube=None) -> dict:
    channel = authorized_channel(youtube)
    wanted = expected_channel_id()
    if channel["id"] != wanted:
        raise RuntimeError(
            f"Authorized {channel['title']} ({channel['id']}), not Somehow True ({wanted}). "
            "Revoke the app at https://myaccount.google.com/permissions, then run "
            "youtube_oauth.py again and pick the Somehow True brand account."
        )
    return channel


def credentials_ready() -> bool:
    return all(
        os.environ.get(name, "").strip()
        for name in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    )


def _credentials() -> Credentials:
    if not credentials_ready():
        raise RuntimeError(
            "YouTube OAuth is missing. Set YOUTUBE_CLIENT_ID, "
            "YOUTUBE_CLIENT_SECRET, and YOUTUBE_REFRESH_TOKEN."
        )
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"].strip(),
        token_uri=TOKEN_URI,
        client_id=os.environ["YOUTUBE_CLIENT_ID"].strip(),
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"].strip(),
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def upload_private(video_path: Path, title: str, description: str, tags: list[str]) -> dict:
    """Upload as private and mark altered/synthetic content. Does not publish."""
    youtube = build("youtube", "v3", credentials=_credentials())
    channel = assert_channel(youtube)
    body = {
        "snippet": {
            "title": youtube_title(title),
            "description": description,
            "tags": tags[:15],
            "categoryId": "27",
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _status, response = request.next_chunk()
    return {
        "video_id": response["id"],
        "channel_id": channel["id"],
        "channel_title": channel["title"],
        "url": f"https://studio.youtube.com/video/{response['id']}/edit",
        "privacyStatus": "private",
        "containsSyntheticMedia": True,
    }


def update_title(video_id: str, title: str) -> dict:
    """Replace the title on an existing video. Leaves description and tags alone."""
    youtube = build("youtube", "v3", credentials=_credentials())
    assert_channel(youtube)
    listed = youtube.videos().list(part="snippet", id=video_id).execute()
    items = listed.get("items") or []
    if not items:
        raise RuntimeError(f"YouTube video {video_id} was not found")
    snippet = items[0]["snippet"]
    snippet["title"] = youtube_title(title)
    youtube.videos().update(part="snippet", body={"id": video_id, "snippet": snippet}).execute()
    return {
        "video_id": video_id,
        "title": snippet["title"],
        "url": f"https://studio.youtube.com/video/{video_id}/edit",
    }
