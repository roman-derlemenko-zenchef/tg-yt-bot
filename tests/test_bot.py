"""Unit tests for the function's request handling. Run from the repo root:

    python3 -m unittest discover -s tests

They stub out Telegram and yt-dlp, so they need neither network nor
dependencies installed (yt_dlp and requests are replaced with stand-ins).
"""

import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

FUNCTION_DIR = os.path.join(os.path.dirname(__file__), "..", "functions", "packages", "tg", "bot")
sys.path.insert(0, os.path.abspath(FUNCTION_DIR))

# Stand-ins so the modules import without the real dependencies.
for name in ("yt_dlp", "yt_dlp.utils", "requests"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["yt_dlp"].utils = sys.modules["yt_dlp.utils"]
sys.modules["yt_dlp.utils"].DownloadError = type("DownloadError", (Exception,), {})
fake_requests = sys.modules["requests"]
fake_requests.RequestException = type("RequestException", (Exception,), {})
fake_requests.ReadTimeout = type("ReadTimeout", (fake_requests.RequestException,), {})
fake_requests.post = None


def load_main():
    """Imports the function's __main__.py under another name."""
    spec = importlib.util.spec_from_file_location("bot_main", os.path.join(FUNCTION_DIR, "__main__.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bot = load_main()

OWNER = 168370115
SECRET = "s3cret"
SELF_URL = "https://tg-yt-bot-abc.ondigitalocean.app/api/tg/bot"


def web_event(message, secret=SECRET):
    return {
        "http": {"headers": {"x-telegram-bot-api-secret-token": secret}, "method": "POST"},
        "update_id": 1,
        "message": message,
    }


def job_event(task, secret=SECRET):
    return {"http": {"headers": {"x-bot-job-secret": secret}, "method": "POST"}, "job": task}


def message(text, chat_id=OWNER, from_id=OWNER):
    return {"message_id": 10, "chat": {"id": chat_id}, "from": {"id": from_id}, "text": text}


class Context:
    pass


@mock.patch.dict(os.environ, {"WEBHOOK_SECRET": SECRET, "APP_URL": "https://tg-yt-bot-abc.ondigitalocean.app"})
class WebhookTest(unittest.TestCase):
    def setUp(self):
        self.send = mock.patch.object(bot.telegram, "send_message", return_value=99).start()
        self.start_job = mock.patch.object(bot, "start_job").start()
        self.run_job = mock.patch.object(bot.job, "run").start()
        self.addCleanup(mock.patch.stopall)

    def test_rejects_wrong_secret(self):
        resp = bot.main(web_event(message("https://youtu.be/dQw4w9WgXcQ"), secret="nope"), Context())
        self.assertEqual(resp["statusCode"], 401)
        self.start_job.assert_not_called()

    def test_ignores_other_users(self):
        resp = bot.main(web_event(message("https://youtu.be/dQw4w9WgXcQ", chat_id=1, from_id=1)), Context())
        self.assertEqual(resp["statusCode"], 200)
        self.send.assert_not_called()
        self.start_job.assert_not_called()

    def test_hands_off_job_for_link(self):
        resp = bot.main(web_event(message("look https://youtu.be/dQw4w9WgXcQ?si=x")), Context())
        self.assertEqual(resp["statusCode"], 200)
        url, task = self.start_job.call_args.args
        self.assertEqual(url, SELF_URL)
        self.assertEqual(task, {"chat_id": OWNER, "url": "https://youtu.be/dQw4w9WgXcQ?si=x",
                                "status_id": 99, "reply_to": 10})
        self.run_job.assert_not_called()

    def test_falls_back_to_inline_job(self):
        self.start_job.side_effect = RuntimeError("unreachable")
        bot.main(web_event(message("https://youtu.be/dQw4w9WgXcQ")), Context())
        self.run_job.assert_called_once()

    def test_help_without_link(self):
        bot.main(web_event(message("/start")), Context())
        self.assertIn("YouTube link", self.send.call_args.args[1])
        self.start_job.assert_not_called()

    def test_errors_still_return_200(self):
        self.send.side_effect = Exception("telegram down")
        resp = bot.main(web_event(message("https://youtu.be/dQw4w9WgXcQ")), Context())
        self.assertEqual(resp["statusCode"], 200)

    def test_job_request_runs_job(self):
        task = {"chat_id": OWNER, "url": "https://youtu.be/dQw4w9WgXcQ"}
        resp = bot.main(job_event(task), Context())
        self.assertEqual(resp["statusCode"], 200)
        self.run_job.assert_called_once_with(task)

    def test_job_request_needs_secret(self):
        resp = bot.main(job_event({"chat_id": OWNER, "url": "u"}, secret="nope"), Context())
        self.assertEqual(resp["statusCode"], 401)
        self.run_job.assert_not_called()

    def test_job_request_only_for_allowed_chats(self):
        resp = bot.main(job_event({"chat_id": 1, "url": "u"}), Context())
        self.assertEqual(resp["statusCode"], 403)
        self.run_job.assert_not_called()

    def test_job_in_telegram_update_is_ignored(self):
        event = web_event(message("hi"))
        event["job"] = {"chat_id": OWNER, "url": "https://youtu.be/dQw4w9WgXcQ"}
        bot.main(event, Context())
        self.run_job.assert_not_called()


@mock.patch.dict(os.environ, {"WEBHOOK_SECRET": SECRET})
class StartJobTest(unittest.TestCase):
    def test_hangs_up_after_handoff(self):
        with mock.patch.object(bot.requests, "post", side_effect=bot.requests.ReadTimeout()) as post:
            bot.start_job(SELF_URL, {"url": "u"})
        self.assertEqual(post.call_args.kwargs["headers"], {"x-bot-job-secret": SECRET})
        self.assertEqual(post.call_args.kwargs["json"], {"job": {"url": "u"}})

    def test_fast_answer_is_a_failure(self):
        resp = mock.Mock(status_code=404, text="not found")
        with mock.patch.object(bot.requests, "post", return_value=resp):
            with self.assertRaises(RuntimeError):
                bot.start_job(SELF_URL, {"url": "u"})


class SelfURLTest(unittest.TestCase):
    @mock.patch.dict(os.environ, {"APP_URL": "https://tg-yt-bot-abc.ondigitalocean.app/"})
    def test_from_app_url(self):
        self.assertEqual(bot.self_url(Context(), {"host": "other.example"}), SELF_URL)

    @mock.patch.dict(os.environ, {"APP_URL": "${APP_URL}"})
    def test_from_forwarded_host_when_app_url_unresolved(self):
        url = bot.self_url(Context(), {"x-forwarded-host": "tg-yt-bot-abc.ondigitalocean.app"})
        self.assertEqual(url, SELF_URL)


class YouTubeURLsTest(unittest.TestCase):
    def test_variants(self):
        cases = {
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
            "youtu.be/dQw4w9WgXcQ": ["https://youtu.be/dQw4w9WgXcQ"],
            "https://youtube.com/shorts/abcdefghijk": ["https://youtube.com/shorts/abcdefghijk"],
            "https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RD": ["https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RD"],
            "https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ": ["https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ"],
            "https://www.youtube.com/@channel": [],
            "https://example.com/watch?v=dQw4w9WgXcQ": [],
        }
        for text, want in cases.items():
            self.assertEqual(bot.youtube_urls(text), want, text)


if __name__ == "__main__":
    unittest.main()
