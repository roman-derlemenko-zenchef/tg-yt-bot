"""Telegram bot that sends back the audio of YouTube links.

Runs as one DigitalOcean Function with two entry paths:

- Web invocation (Telegram's webhook, event has an "http" key): checks the
  webhook secret and the sender, posts a status message and starts a download
  job by invoking this same function asynchronously, then returns at once so
  Telegram doesn't time out and retry.
- Non-web invocation with a "job" parameter: does the download. Only reachable
  through the authenticated Functions API, never from the public URL.
"""

import base64
import hmac
import html
import json
import os
import re
import urllib.request

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


def main(event, context):
    if "http" in event:
        return webhook(event, context)
    if "job" in event:
        job.run(event["job"])
        return {"body": "done"}
    return {"statusCode": 400, "body": "bad request"}


def webhook(event, context):
    headers = event["http"].get("headers") or {}
    secret = os.environ.get("WEBHOOK_SECRET", "")
    got = headers.get("x-telegram-bot-api-secret-token", "")
    if not secret or not hmac.compare_digest(got, secret):
        return {"statusCode": 401, "body": "unauthorized"}

    # From here on, always answer 200: anything else makes Telegram resend the
    # update, which would start the same download again.
    try:
        handle_message(event.get("message") or {}, context)
    except Exception as e:  # noqa: BLE001
        print(f"webhook failed: {e!r}")
    return {"statusCode": 200, "body": ""}


def handle_message(msg, context):
    chat_id = (msg.get("chat") or {}).get("id")
    from_id = (msg.get("from") or {}).get("id")
    if chat_id not in ALLOWED_CHAT_IDS or from_id not in ALLOWED_CHAT_IDS:
        print(f"ignored message from {from_id} in chat {chat_id}")
        return

    text = msg.get("text") or msg.get("caption") or ""
    urls = youtube_urls(text)
    if not urls:
        telegram.send_message(chat_id, HELP)
        return

    for url in urls:
        status_id = telegram.send_message(chat_id, f'🎵 <a href="{html.escape(url)}">YouTube link</a>\n\n⏳ Starting…')
        task = {"chat_id": chat_id, "url": url, "status_id": status_id, "reply_to": msg.get("message_id")}
        try:
            start_async(context, task)
        except Exception as e:  # noqa: BLE001
            # Without async invocation the download runs inside the webhook
            # call. Fine for most videos; a slow one risks Telegram retrying.
            print(f"async invoke unavailable ({e!r}), running inline")
            job.run(task)


def youtube_urls(text):
    urls = YOUTUBE_URL.findall(text)
    return [u if u.lower().startswith("http") else "https://" + u for u in urls]


def start_async(context, task):
    """Invokes this function again, non-blocking, through the Functions REST
    API. The API key is only in the context because project.yml sets the
    provide-api-key annotation."""
    api_host = getattr(context, "api_host", None) or os.environ.get("__OW_API_HOST")
    api_key = getattr(context, "api_key", None) or os.environ.get("__OW_API_KEY")
    name = getattr(context, "function_name", None) or os.environ.get("__OW_ACTION_NAME")
    if not (api_host and api_key and name):
        raise RuntimeError("no API host/key in the invocation context")
    if not api_host.startswith("http"):
        api_host = "https://" + api_host

    # name is "/<namespace>/<package>/<function>".
    namespace, _, action = name.strip("/").partition("/")
    url = f"{api_host}/api/v1/namespaces/{namespace}/actions/{action}?blocking=false"
    req = urllib.request.Request(
        url,
        data=json.dumps({"job": task}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Basic " + base64.b64encode(api_key.encode()).decode(),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"started download {json.load(resp).get('activationId')} for {task['url']}")
