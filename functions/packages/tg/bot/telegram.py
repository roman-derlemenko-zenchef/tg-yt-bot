"""Minimal Telegram Bot API client: just the calls this bot needs."""

import os

import requests

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    pass


def call(method, files=None, timeout=30, **params):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    url = API.format(token=token, method=method)
    try:
        if files:
            resp = requests.post(url, data=params, files=files, timeout=timeout)
        else:
            resp = requests.post(url, json=params, timeout=timeout)
    except requests.RequestException as e:
        # The exception text contains the URL, and with it the token.
        raise TelegramError(f"{method}: {type(e).__name__}") from None
    body = resp.json()
    if not body.get("ok"):
        raise TelegramError(f"{method}: {body.get('description', resp.status_code)}")
    return body["result"]


def send_message(chat_id, html, reply_to=None):
    params = dict(chat_id=chat_id, text=html, parse_mode="HTML", link_preview_options={"is_disabled": True})
    if reply_to:
        params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    return call("sendMessage", **params)["message_id"]


def edit_message(chat_id, message_id, html):
    try:
        call("editMessageText", chat_id=chat_id, message_id=message_id, text=html,
             parse_mode="HTML", link_preview_options={"is_disabled": True})
    except TelegramError as e:
        if "message is not modified" not in str(e):
            raise


def delete_message(chat_id, message_id):
    call("deleteMessage", chat_id=chat_id, message_id=message_id)


def send_audio(chat_id, path, *, title, performer, duration, caption, thumbnail=None, reply_to=None):
    """Uploads an m4a/mp3 as a playable audio message (bots may upload up to 50 MB)."""
    params = dict(chat_id=chat_id, title=title, performer=performer, caption=caption, parse_mode="HTML")
    if duration:
        params["duration"] = int(duration)
    if reply_to:
        params["reply_to_message_id"] = reply_to
    with open(path, "rb") as f:
        files = {"audio": (os.path.basename(path), f)}
        if thumbnail:
            files["thumbnail"] = ("thumb.jpg", thumbnail, "image/jpeg")
        return call("sendAudio", files=files, timeout=600, **params)


def send_document(chat_id, path, *, caption, reply_to=None):
    """For audio formats Telegram's player doesn't take (e.g. webm/opus)."""
    params = dict(chat_id=chat_id, caption=caption, parse_mode="HTML")
    if reply_to:
        params["reply_to_message_id"] = reply_to
    with open(path, "rb") as f:
        return call("sendDocument", files={"document": (os.path.basename(path), f)}, timeout=600, **params)
