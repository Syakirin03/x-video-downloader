"""Twitter / X video downloader - Flask web app.

Run:  python app.py   then open http://127.0.0.1:8000
"""

import os
import re
from urllib.parse import urlparse

import requests
from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from extractor import USER_AGENT, ExtractError, extract

app = Flask(__name__)

# The download proxy only ever fetches from Twitter's video CDN, so it can't be
# abused to make the server request arbitrary URLs.
ALLOWED_MEDIA_HOSTS = {"video.twimg.com"}
PASSTHROUGH_HEADERS = ("Content-Length", "Content-Range", "Accept-Ranges", "Last-Modified", "ETag")


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/extract")
def api_extract():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(extract(payload.get("url", "")))
    except ExtractError as e:
        return jsonify(error=str(e)), 400
    except Exception:
        app.logger.exception("Extraction failed")
        return jsonify(error="Something went wrong while reading that post. Try again."), 500


@app.get("/api/download")
def api_download():
    url = request.args.get("url", "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_MEDIA_HOSTS:
        return jsonify(error="Invalid media URL."), 400

    upstream_headers = {"User-Agent": USER_AGENT}
    if "Range" in request.headers:  # lets the in-page preview player seek
        upstream_headers["Range"] = request.headers["Range"]
    try:
        upstream = requests.get(url, headers=upstream_headers, stream=True, timeout=(10, 60))
    except requests.RequestException:
        return jsonify(error="Couldn't reach Twitter's video server."), 502
    if upstream.status_code not in (200, 206):
        upstream.close()
        return jsonify(error="The video is no longer available."), 502

    headers = {h: upstream.headers[h] for h in PASSTHROUGH_HEADERS if h in upstream.headers}
    headers["Content-Type"] = upstream.headers.get("Content-Type", "video/mp4")
    headers["Cache-Control"] = "no-store"
    if request.args.get("inline") != "1":
        filename = _safe_filename(request.args.get("filename")) or "twitter-video.mp4"
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    def stream():
        try:
            yield from upstream.iter_content(chunk_size=256 * 1024)
        finally:
            upstream.close()

    return Response(stream_with_context(stream()), status=upstream.status_code, headers=headers)


def _safe_filename(name):
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "").strip("._")[:120]
    if name and not name.lower().endswith(".mp4"):
        name += ".mp4"
    return name


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"\n  Twitter Video Downloader running at http://{host}:{port}\n")
    app.run(host=host, port=port, threaded=True)
