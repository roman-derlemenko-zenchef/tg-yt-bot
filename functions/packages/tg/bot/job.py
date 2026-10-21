"""Downloads the audio of one YouTube link and sends it back, reporting
progress by editing a single status message."""

import html
import os
import shutil
import stat
import tempfile
import time

import requests
import yt_dlp

import telegram

# Bots can upload at most 50 MB. Pick the best m4a (AAC, playable in
# Telegram's audio player) that fits; YouTube usually also offers a ~48 kbps
# m4a, which covers long videos. There is no ffmpeg in the Functions runtime,
# so nothing is converted: whatever is picked is sent as-is.
FORMAT = ("ba[ext=m4a][filesize<49M]/ba[ext=m4a][filesize_approx<49M]"
          "/ba[filesize<49M]/ba[filesize_approx<49M]")
UPLOAD_LIMIT = 50 * 1000 * 1000
STATUS_EVERY = 2.0  # seconds; Telegram rate-limits message edits

HERE = os.path.dirname(os.path.abspath(__file__))


def run(job):
    chat_id, url = job["chat_id"], job["url"]
    status = Status(chat_id, job.get("status_id"), url)
    status.update("🔎 Fetching video info…", force=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            info, path = download(url, tmp, status)
            status.set_info(info)
            size = os.path.getsize(path)
            if size > UPLOAD_LIMIT:
                raise JobError(f"The audio is {mb(size)}, over Telegram's 50 MB limit for bots.")
            status.update(f"📤 Uploading {mb(size)}…", force=True)
            send(chat_id, path, info, url, job.get("reply_to"))
    except JobError as e:
        status.update("❌ " + html.escape(str(e)), force=True)
        return
    except Exception as e:  # noqa: BLE001 - report anything to the chat
        print(f"job failed for {url}: {e!r}")
        status.update("❌ " + html.escape(f"{type(e).__name__}: {e}"), force=True)
        return
    status.delete()


class JobError(Exception):
    pass


def download(url, tmp, status):
    def hook(d):
        status.set_info(d.get("info_dict") or {})
        if d["status"] != "downloading":
            return
        done = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        pct = done / total * 100 if total else 0
        speed = d.get("speed") or 0
        eta = d.get("eta")
        line = f"⬇️ Downloading {bar(pct)} {pct:.0f}%\n{mb(total)} · {mb(speed)}/s"
        if eta is not None:
            line += f" · ETA {int(eta)}s"
        status.update(line)

    opts = {
        "format": FORMAT,
        "outtmpl": os.path.join(tmp, "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "fixup": "never",  # needs ffmpeg
        "cachedir": False,  # $HOME may not be writable in the runtime
        "js_runtimes": {"quickjs": {"path": quickjs()}},
        "progress_hooks": [hook],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e).removeprefix("ERROR: ").strip()
        if "Requested format is not available" in msg:
            msg = "There's no audio version under 50 MB (Telegram's upload limit for bots)."
        raise JobError(msg) from None
    downloads = info.get("requested_downloads") or []
    path = downloads[0].get("filepath") if downloads else None
    if not path or not os.path.exists(path):
        raise JobError("yt-dlp finished without producing a file.")
    return info, path


def send(chat_id, path, info, url, reply_to):
    title = info.get("title") or "YouTube audio"
    caption = f'🔗 <a href="{html.escape(url)}">{html.escape(title)}</a>'
    if path.endswith((".m4a", ".mp3")):
        telegram.send_audio(
            chat_id, path,
            title=title,
            performer=info.get("uploader") or info.get("channel") or "",
            duration=info.get("duration"),
            caption=caption,
            thumbnail=thumbnail(info.get("id")),
            reply_to=reply_to,
        )
    else:
        telegram.send_document(chat_id, path, caption=caption, reply_to=reply_to)


def thumbnail(video_id):
    """YouTube's 320x180 "mqdefault" cover already fits Telegram's limits for
    audio thumbnails (JPEG, at most 320 px and 200 kB)."""
    if not video_id:
        return None
    try:
        resp = requests.get(f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg", timeout=10)
    except requests.RequestException:
        return None
    if resp.status_code != 200 or len(resp.content) > 200_000:
        return None
    return resp.content


def quickjs():
    """Path of the bundled QuickJS binary. Deployment may drop the executable
    bit, so fall back to an executable copy in /tmp."""
    src = os.path.join(HERE, "bin", "qjs")
    if os.access(src, os.X_OK):
        return src
    dst = os.path.join(tempfile.gettempdir(), "qjs")
    if not os.access(dst, os.X_OK):
        shutil.copyfile(src, dst)
        os.chmod(dst, os.stat(dst).st_mode | stat.S_IXUSR)
    return dst


class Status:
    """The status message: a header about the video plus the current stage."""

    def __init__(self, chat_id, message_id, url):
        self.chat_id, self.message_id, self.url = chat_id, message_id, url
        self.title = self.uploader = None
        self.duration = 0
        self.last_text, self.last_edit = None, 0.0

    def set_info(self, info):
        self.title = info.get("title") or self.title
        self.uploader = info.get("uploader") or info.get("channel") or self.uploader
        self.duration = info.get("duration") or self.duration

    def header(self):
        if not self.title:
            return f'🎵 <a href="{html.escape(self.url)}">YouTube link</a>'
        h = f"🎵 <b>{html.escape(self.title)}</b>"
        meta = []
        if self.uploader:
            meta.append("👤 " + html.escape(self.uploader))
        if self.duration:
            meta.append("⏱ " + duration(self.duration))
        return h + ("\n" + " · ".join(meta) if meta else "")

    def update(self, line, force=False):
        now = time.monotonic()
        if not force and now - self.last_edit < STATUS_EVERY:
            return
        text = f"{self.header()}\n\n{line}"
        if text == self.last_text:
            return
        self.last_text, self.last_edit = text, now
        try:
            if self.message_id:
                telegram.edit_message(self.chat_id, self.message_id, text)
            else:
                self.message_id = telegram.send_message(self.chat_id, text)
        except telegram.TelegramError as e:
            print(f"status update failed: {e}")

    def delete(self):
        """The audio message speaks for itself once it's there."""
        if self.message_id:
            try:
                telegram.delete_message(self.chat_id, self.message_id)
            except telegram.TelegramError as e:
                print(f"status delete failed: {e}")


def bar(pct):
    filled = min(max(round(pct / 10), 0), 10)
    return "▓" * filled + "░" * (10 - filled)


def mb(n):
    return f"{(n or 0) / 1e6:.1f} MB"


def duration(seconds):
    s = int(seconds)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
