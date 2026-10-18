"""Find the downloadable MP4 files behind a Twitter / X post.

Strategy:
  1. Twitter's public embed endpoint (cdn.syndication.twimg.com) - fast, no login,
     covers normal videos and GIFs.
  2. yt-dlp as a fallback - covers card videos (polls, promoted posts, etc.).
"""

import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
SYNDICATION_URL = "https://cdn.syndication.twimg.com/tweet-result"

TWEET_HOSTS = {
    "twitter.com", "x.com", "mobile.twitter.com", "mobile.x.com",
    "fxtwitter.com", "vxtwitter.com", "fixupx.com", "fixvx.com", "twittpr.com",
}
STATUS_RE = re.compile(r"/(?:i/web/|i/)?(?:[A-Za-z0-9_]+/)?status(?:es)?/(\d{5,25})")
RESOLUTION_RE = re.compile(r"/(\d{2,5})x(\d{2,5})/")


class ExtractError(Exception):
    """An error whose message is safe to show to the user."""


def parse_tweet_id(text):
    """Return the numeric tweet ID from a URL (or a bare ID), or raise ExtractError."""
    text = (text or "").strip()
    if not text:
        raise ExtractError("Please paste a Twitter / X link.")
    if text.isdigit():
        return text
    if not re.match(r"^https?://", text, re.I):
        text = "https://" + text

    parsed = urlparse(text)
    host = (parsed.hostname or "").lower().removeprefix("www.")

    if host == "t.co":
        text = _resolve_short_link(text)
        parsed = urlparse(text)
        host = (parsed.hostname or "").lower().removeprefix("www.")

    if host not in TWEET_HOSTS:
        raise ExtractError("That doesn't look like a Twitter / X link.")
    match = STATUS_RE.search(parsed.path)
    if not match:
        raise ExtractError("Link a specific post - it should contain /status/<number>.")
    return match.group(1)


def _resolve_short_link(url):
    try:
        resp = requests.head(url, allow_redirects=True, timeout=10,
                             headers={"User-Agent": USER_AGENT})
        return resp.url
    except requests.RequestException:
        raise ExtractError("Couldn't open that t.co short link.")


def extract(url):
    """Return a dict describing the post and every video in it."""
    tweet_id = parse_tweet_id(url)

    result = _from_syndication(tweet_id)
    if result and result["media"]:
        return _with_file_sizes(result)

    fallback = _from_ytdlp(tweet_id)
    if fallback and fallback["media"]:
        return _with_file_sizes(fallback)

    if result is None and fallback is None:
        raise ExtractError("This post is unavailable - it may be deleted, private, "
                           "or age-restricted.")
    raise ExtractError("No video or GIF found in this post.")


# --- Source 1: syndication (embed) endpoint ---------------------------------

def _syndication_token(tweet_id):
    """Port of the embed widget's token: ((id / 1e15) * PI).toString(36) minus 0s and dots."""
    value = (int(tweet_id) / 1e15) * math.pi
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    whole, frac = int(value), value - int(value)
    out = ""
    while whole:
        out = digits[whole % 36] + out
        whole //= 36
    out = (out or "0") + "."
    for _ in range(11):
        frac *= 36
        out += digits[int(frac)]
        frac -= int(frac)
    return re.sub(r"(0+|\.)", "", out)


def _from_syndication(tweet_id):
    """Return a result dict, or None if the post is unavailable through this source."""
    try:
        resp = requests.get(
            SYNDICATION_URL,
            params={"id": tweet_id, "lang": "en", "token": _syndication_token(tweet_id)},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200 or not resp.text.strip():
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    if data.get("tombstone") or data.get("__typename") == "TweetTombstone":
        return None

    media = _syndication_media(data)
    # A post quoting a video: offer the quoted video when the post has none of its own.
    if not media and isinstance(data.get("quoted_tweet"), dict):
        media = _syndication_media(data["quoted_tweet"])

    user = data.get("user") or {}
    return {
        "id": tweet_id,
        "text": _clean_text(data.get("text", "")),
        "created_at": data.get("created_at"),
        "author": {
            "name": user.get("name"),
            "username": user.get("screen_name"),
            "avatar": user.get("profile_image_url_https"),
        },
        "media": media,
        "source": "embed",
    }


def _syndication_media(tweet):
    items = []
    for m in tweet.get("mediaDetails") or []:
        if m.get("type") not in ("video", "animated_gif"):
            continue
        info = m.get("video_info") or {}
        duration = (info.get("duration_millis") or 0) / 1000 or None
        variants = []
        for v in info.get("variants") or []:
            if v.get("content_type") != "video/mp4" or not v.get("url"):
                continue
            width, height = _resolution_from_url(v["url"])
            if not width:  # GIF URLs carry no resolution; use the original's
                original = m.get("original_info") or {}
                width, height = original.get("width"), original.get("height")
            variants.append({"url": v["url"], "width": width, "height": height,
                             "bitrate": v.get("bitrate") or None, "size": None})
        if variants:
            items.append({
                "type": "gif" if m["type"] == "animated_gif" else "video",
                "thumbnail": m.get("media_url_https"),
                "duration": duration,
                "variants": _sort_variants(variants),
            })
    return items


# --- Source 2: yt-dlp fallback ----------------------------------------------

def _from_ytdlp(tweet_id):
    try:
        import yt_dlp
    except ImportError:
        return None

    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": False}
    cookies = os.environ.get("TWDL_COOKIES")
    if cookies:
        opts["cookiefile"] = cookies
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://x.com/i/status/{tweet_id}", download=False)
    except Exception:
        return None
    if not info:
        return None

    entries = [e for e in (info.get("entries") or [info]) if e]
    media = []
    for entry in entries:
        variants = []
        for f in entry.get("formats") or []:
            url = f.get("url") or ""
            if f.get("protocol") not in ("http", "https") or f.get("ext") != "mp4":
                continue
            if urlparse(url).hostname != "video.twimg.com":
                continue
            width, height = f.get("width"), f.get("height")
            if not (width and height):
                width, height = _resolution_from_url(url)
            variants.append({"url": url, "width": width, "height": height,
                             "bitrate": int(f["tbr"] * 1000) if f.get("tbr") else None,
                             "size": f.get("filesize")})
        if variants:
            media.append({
                "type": "video",
                "thumbnail": entry.get("thumbnail"),
                "duration": entry.get("duration"),
                "variants": _sort_variants(variants),
            })

    first = entries[0] if entries else info
    return {
        "id": tweet_id,
        "text": _clean_text(first.get("description") or ""),
        "created_at": None,
        "author": {
            "name": first.get("uploader"),
            "username": first.get("uploader_id"),
            "avatar": None,
        },
        "media": media,
        "source": "yt-dlp",
    }


# --- Helpers ----------------------------------------------------------------

def _with_file_sizes(result):
    """Fill in exact file sizes with parallel HEAD requests (Twitter's listed
    bitrates are ceilings, so estimating from them overstates size ~3x)."""
    variants = [v for m in result["media"] for v in m["variants"] if not v["size"]]

    def head(v):
        try:
            resp = requests.head(v["url"], headers={"User-Agent": USER_AGENT},
                                 timeout=5, allow_redirects=True)
            if resp.ok and resp.headers.get("Content-Length", "").isdigit():
                v["size"] = int(resp.headers["Content-Length"])
        except requests.RequestException:
            pass  # size is optional; the UI just omits it

    if variants:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(head, variants))
    return result


def _resolution_from_url(url):
    match = RESOLUTION_RE.search(url)
    return (int(match.group(1)), int(match.group(2))) if match else (None, None)


def _sort_variants(variants):
    """Highest quality first, one entry per resolution."""
    variants.sort(key=lambda v: ((v["width"] or 0) * (v["height"] or 0), v["bitrate"] or 0),
                  reverse=True)
    seen, unique = set(), []
    for v in variants:
        key = (v["width"], v["height"]) if v["width"] else v["url"]
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return unique


def _clean_text(text):
    # Drop the trailing t.co link Twitter appends for attached media.
    return re.sub(r"\s*https://t\.co/\w+\s*$", "", text).strip()
