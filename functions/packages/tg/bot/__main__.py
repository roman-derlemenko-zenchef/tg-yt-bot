"""Telegram bot that sends back the audio of YouTube links.

Runs as one DigitalOcean web function that is called in two ways:

- By Telegram's webhook (X-Telegram-Bot-Api-Secret-Token header): checks the
  secret and the sender, posts a status message, starts a download job and
  returns at once, so Telegram doesn't time out and resend the update.
- By itself, to run a job (X-Bot-Job-Secret header, "job" in the body). The
  webhook call fires this request and hangs up after a moment: Functions keeps
  running an invocation after its caller disconnects, up to the function's
  15-minute limit. App Platform doesn't allow giving a function an API key, so
  the Functions API's own async invocation isn't available.
"""

import hmac
import html
import os
import re

import requests

import job
import telegram

# The only Telegram users (and private chats) the bot works for. Messages
# from anyone else are ignored without a reply.
ALLOWED_CHAT_IDS = {168370115}

YOUTUBE_URL = re.compile(
    r"(?i)(?:https?://)?(?:(?:www|m|music)\.)?"
    r"(?:youtube\.com/(?:watch\?\S*?v=|shorts/|live/|embed/)|youtu\.be/)"
    r"[A-Za-z0-9_-]{11}\S*"
)

HELP = "🎵 Send me a YouTube link (video, short, youtu.be or YouTube Music) and I'll send back its audio."

JOB_HEADER = "x-bot-job-secret"
# How long the webhook call waits on the job request before hanging up. Long
# enough for the request to be delivered, short enough for Telegram.
JOB_HANDOFF_WAIT = 2


def main(event, context):
    http = event.get("http")
    if not http:
        return {"statusCode": 400, "body": "web calls only"}
    headers = http.get("headers") or {}
    secret = os.environ.get("WEBHOOK_SECRET", "")
    if not secret:
        return {"statusCode": 500, "body": "not configured"}

    if secret_matches(headers.get(JOB_HEADER), secret):
        task = event.get("job") or {}
        if task.get("chat_id") not in ALLOWED_CHAT_IDS:
            return {"statusCode": 403, "body": "forbidden"}
        job.run(task)
        return {"statusCode": 200, "body": "done"}

    if not secret_matches(headers.get("x-telegram-bot-api-secret-token"), secret):
        return {"statusCode": 401, "body": "unauthorized"}

    # From here on, always answer 200: anything else makes Telegram resend the
    # update, which would start the same download again.
    outcomes = []
    try:
        outcomes = handle_message(event.get("message") or {}, self_url(context, headers))
    except Exception as e:  # noqa: BLE001
        print(f"webhook failed: {e!r}")
        outcomes = [f"error: {e!r}"]
    # Telegram ignores the response; the header is for debugging by hand.
    return {"statusCode": 200, "body": "", "headers": {"X-Job-Handoff": "; ".join(outcomes)[:500]}}


def secret_matches(got, secret):
    return bool(got) and hmac.compare_digest(got, secret)


def handle_message(msg, url_of_self):
    """Returns one line per link saying how its job was started."""
    chat_id = (msg.get("chat") or {}).get("id")
    from_id = (msg.get("from") or {}).get("id")
    if chat_id not in ALLOWED_CHAT_IDS or from_id not in ALLOWED_CHAT_IDS:
        print(f"ignored message from {from_id} in chat {chat_id}")
        return ["ignored"]

    text = msg.get("text") or msg.get("caption") or ""
    urls = youtube_urls(text)
    if not urls:
        telegram.send_message(chat_id, HELP)
        return ["help"]

    outcomes = []
    for url in urls:
        status_id = telegram.send_message(chat_id, f'🎵 <a href="{html.escape(url)}">YouTube link</a>\n\n⏳ Starting…')
        task = {"chat_id": chat_id, "url": url, "status_id": status_id, "reply_to": msg.get("message_id")}
        try:
            start_job(url_of_self, task)
            outcomes.append(f"started via {url_of_self}")
        except Exception as e:  # noqa: BLE001
            # The download then runs inside the webhook call. Fine for most
            # videos; a slow one risks Telegram resending the update.
            print(f"job hand-off failed ({e!r}), running inline")
            outcomes.append(f"inline, hand-off to {url_of_self} failed: {e!r}")
            job.run(task)
    return outcomes


def youtube_urls(text):
    urls = YOUTUBE_URL.findall(text)
    return [u if u.lower().startswith("http") else "https://" + u for u in urls]


# Where App Platform serves this function: the ingress route in main.tf plus
# "/<package>/<function>" from project.yml. (The function's own Functions web
# URL, on doserverless.co, returns 404 for App Platform functions.)
ROUTE = "/api/tg/bot"


def self_url(context, headers):
    """This function's public URL, from the app's live URL (APP_URL, set by
    App Platform) or else the host the webhook call came in on."""
    app_url = os.environ.get("APP_URL", "")
    if app_url.startswith("https://"):
        return app_url.rstrip("/") + ROUTE
    host = headers.get("x-forwarded-host") or headers.get("host")
    return f"https://{host}{ROUTE}" if host else None


def start_job(url, task):
    """Sends the job to this function and hangs up without waiting for it."""
    if not url:
        raise RuntimeError("own URL unknown")
    try:
        resp = requests.post(
            url,
            json={"job": task},
            headers={JOB_HEADER: os.environ["WEBHOOK_SECRET"]},
            timeout=(5, JOB_HANDOFF_WAIT),  # (connect, read)
        )
    except requests.ReadTimeout:
        print(f"started download of {task['url']} via {url}")
        return
    # An answer this fast means the job didn't run (or failed immediately).
    raise RuntimeError(f"job request returned {resp.status_code}: {resp.text[:200]}")
