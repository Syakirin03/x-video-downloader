# X Video Downloader

A small web app for saving videos and GIFs from Twitter / X posts as MP4.

## Run it

Double-click `run.bat`. The first run creates a virtual environment and installs dependencies.
Your browser then opens at http://127.0.0.1:8000.

Or start it manually:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

## Use it

Paste a post link (`x.com/.../status/...`, `twitter.com/...`, `t.co/...`, `fxtwitter.com/...`, or a bare post ID).
Each video in the post appears with every available resolution. Click **MP4** to download, or click the thumbnail to preview it.

You can also open `http://127.0.0.1:8000/?url=<post link>` to start a lookup straight away.

## How it works

| Piece | What it does |
| --- | --- |
| `extractor.py` | Gets the post's ID and finds its MP4 files. It tries Twitter's public embed endpoint first (fast, no login). If that finds no video, for example on poll or promoted "card" videos, it falls back to **yt-dlp**. |
| `app.py` | Flask server. `POST /api/extract` returns the post's details and video options. `GET /api/download` streams the MP4 from `video.twimg.com` with a download header so the browser saves the file. The download route only accepts `video.twimg.com` URLs, so nobody can use it as an open proxy. |
| `templates/`, `static/` | The page (plain HTML, CSS, and JS; light and dark mode; works on phones). |

## Options

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Set to `0.0.0.0` to use the app from other devices on your network. |
| `PORT` | `8000` | Port to listen on. |
| `TWDL_COOKIES` | (unset) | Path to a Netscape-format `cookies.txt` for x.com. yt-dlp uses it for age-restricted posts that need a login. |

Keep any cookies file **outside this folder**, because it gives full access to your X account. `.gitignore` also blocks files named like `cookies.txt` from being committed, as a backup.

## Limits

- Only public posts work. Private, deleted, and most age-restricted posts can't be fetched without cookies.
- Twitter Spaces and live broadcasts aren't supported.
- If downloads stop working after Twitter changes something, update yt-dlp: `.venv\Scripts\pip install -U yt-dlp`.
- Only download content you have the right to use.
