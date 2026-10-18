(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const form = $("#form");
  const input = $("#url");
  const submit = $("#submit");
  const pasteBtn = $("#paste");
  const clearBtn = $("#clear");
  const status = $("#status");
  const results = $("#results");

  const TWEET_LINK = /(twitter\.com|x\.com|t\.co|fxtwitter\.com|vxtwitter\.com|fixupx\.com)\/\S+|^\d{8,25}$/i;
  let busy = false;

  // --- Input helpers -------------------------------------------------------

  if (navigator.clipboard && navigator.clipboard.readText) pasteBtn.hidden = false;

  function syncInputButtons() {
    const hasText = input.value.trim().length > 0;
    clearBtn.hidden = !hasText;
    if (navigator.clipboard && navigator.clipboard.readText) pasteBtn.hidden = hasText;
  }
  input.addEventListener("input", syncInputButtons);

  pasteBtn.addEventListener("click", async () => {
    try {
      input.value = (await navigator.clipboard.readText()).trim();
      syncInputButtons();
      if (TWEET_LINK.test(input.value)) form.requestSubmit();
      else input.focus();
    } catch {
      input.focus();
      showStatus("Clipboard access was blocked. Paste with Ctrl+V instead.", "info");
    }
  });

  clearBtn.addEventListener("click", () => {
    input.value = "";
    syncInputButtons();
    clearResults();
    input.focus();
  });

  // Pasting a link starts the lookup straight away.
  input.addEventListener("paste", () => {
    setTimeout(() => {
      syncInputButtons();
      if (TWEET_LINK.test(input.value.trim())) form.requestSubmit();
    });
  });

  // --- Lookup --------------------------------------------------------------

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = input.value.trim();
    if (!url) {
      showStatus("Paste a Twitter / X post link first.");
      input.focus();
      return;
    }
    if (busy) return;
    setBusy(true);
    clearResults();

    try {
      const res = await fetch("/api/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Couldn't read that post.");
      renderResult(data);
      history.replaceState(null, "", "?url=" + encodeURIComponent(url));
    } catch (err) {
      showStatus(err.message === "Failed to fetch"
        ? "Can't reach the server. Is app.py still running?"
        : err.message);
    } finally {
      setBusy(false);
    }
  });

  function setBusy(on) {
    busy = on;
    submit.classList.toggle("loading", on);
    $(".label", submit).textContent = on ? "Fetching…" : "Download";
  }

  function showStatus(msg, kind = "error") {
    status.textContent = msg;
    status.className = "status" + (kind === "info" ? " info" : "");
  }

  function clearResults() {
    status.textContent = "";
    results.replaceChildren();
    document.body.classList.remove("results-shown");
  }

  // --- Rendering -----------------------------------------------------------

  function renderResult(data) {
    const card = $("#tpl-result").content.firstElementChild.cloneNode(true);
    const { author = {} } = data;
    const username = author.username || "";
    const postUrl = `https://x.com/${username || "i"}/status/${data.id}`;

    $(".name", card).textContent = author.name || (username ? "@" + username : "Twitter / X post");
    const handle = $(".handle", card);
    if (username) {
      handle.textContent = "@" + username;
      handle.href = `https://x.com/${username}`;
    } else {
      handle.remove();
    }
    if (author.avatar) {
      const img = $(".avatar", card);
      img.src = author.avatar;
      img.hidden = false;
    }
    $(".open-post", card).href = postUrl;
    $(".text", card).textContent = data.text || "";

    const list = $(".media-list", card);
    data.media.forEach((media, i) => {
      list.append(renderMedia(media, i, data.media.length, data.id, username));
    });

    results.append(card);
    document.body.classList.add("results-shown");
  }

  function renderMedia(media, index, total, tweetId, username) {
    const el = $("#tpl-media").content.firstElementChild.cloneNode(true);
    const thumb = $(".thumb", el);
    const kind = media.type === "gif" ? "GIF" : "Video";

    if (media.thumbnail) $("img", thumb).src = media.thumbnail;
    if (media.type === "gif") $(".kind", thumb).hidden = false;
    if (media.duration) {
      const d = $(".duration", thumb);
      d.textContent = formatDuration(media.duration);
      d.hidden = false;
    }
    $(".media-title", el).textContent = total > 1 ? `${kind} ${index + 1} of ${total}` : kind;

    // Clicking the thumbnail swaps in a player (a mid-quality copy loads faster).
    thumb.addEventListener("click", () => {
      const pick = media.variants.find((v) => shortSide(v) && shortSide(v) <= 720) || media.variants[0];
      const video = document.createElement("video");
      video.controls = true;
      video.autoplay = true;
      video.playsInline = true;
      if (media.type === "gif") video.loop = true;
      if (media.thumbnail) video.poster = media.thumbnail;
      video.src = proxyUrl(pick.url, null, true);
      thumb.replaceWith(video);
    });

    const ul = $(".variants", el);
    media.variants.forEach((v, vi) => {
      const li = $("#tpl-variant").content.firstElementChild.cloneNode(true);
      const side = shortSide(v);
      const res = $(".res", li);
      res.textContent = side ? `${side}p` : "MP4";
      if (vi === 0 && media.variants.length > 1) {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = "Best";
        res.append(tag);
      }

      const meta = [];
      if (v.width && v.height) meta.push(`${v.width} × ${v.height}`);
      if (v.bitrate) meta.push(formatBitrate(v.bitrate));
      if (v.size) meta.push(formatBytes(v.size));
      $(".meta", li).textContent = meta.join(" · ") || "Original quality";

      const name = [username || "twitter", tweetId, total > 1 ? index + 1 : null, side ? side + "p" : null]
        .filter(Boolean).join("_") + ".mp4";
      const dl = $(".dl", li);
      dl.href = proxyUrl(v.url, name);
      dl.download = name;
      dl.setAttribute("aria-label", `Download ${res.firstChild.textContent} MP4`);

      const copy = $(".copy", li);
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(v.url);
          copy.textContent = "Copied";
          copy.classList.add("done");
          setTimeout(() => { copy.textContent = "Copy link"; copy.classList.remove("done"); }, 1600);
        } catch {
          window.prompt("Copy this video link:", v.url);
        }
      });
      ul.append(li);
    });
    return el;
  }

  // --- Formatting ----------------------------------------------------------

  function proxyUrl(url, filename, inline = false) {
    const p = new URLSearchParams({ url });
    if (filename) p.set("filename", filename);
    if (inline) p.set("inline", "1");
    return "/api/download?" + p.toString();
  }

  function shortSide(v) {
    return v.width && v.height ? Math.min(v.width, v.height) : null;
  }

  function formatDuration(sec) {
    const s = Math.round(sec);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    const mm = h ? String(m).padStart(2, "0") : m;
    return (h ? h + ":" : "") + mm + ":" + String(r).padStart(2, "0");
  }

  function formatBitrate(bps) {
    return bps >= 1e6 ? (bps / 1e6).toFixed(1) + " Mbps" : Math.round(bps / 1e3) + " kbps";
  }

  function formatBytes(n) {
    if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(2) + " GB";
    if (n >= 1024 ** 2) return (n / 1024 ** 2).toFixed(1) + " MB";
    return Math.max(1, Math.round(n / 1024)) + " KB";
  }

  // --- Deep link: /?url=<post link> runs immediately ------------------------

  const initial = new URLSearchParams(location.search).get("url");
  if (initial) {
    input.value = initial;
    syncInputButtons();
    form.requestSubmit();
  }
})();
