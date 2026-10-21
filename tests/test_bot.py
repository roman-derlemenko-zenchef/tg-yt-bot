"""Unit tests for the function's request handling. Run from the repo root:

    python3 -m unittest discover -s tests

They stub out Telegram and yt-dlp, so they need neither network nor
dependencies installed (yt_dlp and requests are replaced with stand-ins).
"""

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
sys.modules["requests"].RequestException = type("RequestException", (Exception,), {})

import importlib.util  # noqa: E402


def load_main():
    """Imports the function's __main__.py under another name."""
    spec = importlib.util.spec_from_file_location("bot_main", os.path.join(FUNCTION_DIR, "__main__.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bot = load_main()

OWNER = 168370115
SECRET = "s3cret"


def web_event(message, secret=SECRET):
    return {
        "http": {"headers": {"x-telegram-bot-api-secret-token": secret}, "method": "POST"},
        "update_id": 1,
        "message": message,
    }


def message(text, chat_id=OWNER, from_id=OWNER):
    return {"message_id": 10, "chat": {"id": chat_id}, "from": {"id": from_id}, "text": text}


class Context:
    api_host = "https://faas-fra1-example.doserverless.co"
    api_key = "user:pass"
    function_name = "/fn-abc/tg/bot"


@mock.patch.dict(os.environ, {"WEBHOOK_SECRET": SECRET})
class WebhookTest(unittest.TestCase):
    def setUp(self):
        self.send = mock.patch.object(bot.telegram, "send_message", return_value=99).start()
        self.start_async = mock.patch.object(bot, "start_async").start()
        self.run_job = mock.patch.object(bot.job, "run").start()
        self.addCleanup(mock.patch.stopall)

    def test_rejects_wrong_secret(self):
        resp = bot.main(web_event(message("https://youtu.be/dQw4w9WgXcQ"), secret="nope"), Context())
        self.assertEqual(resp["statusCode"], 401)
        self.start_async.assert_not_called()

    def test_ignores_other_users(self):
        resp = bot.main(web_event(message("https://youtu.be/dQw4w9WgXcQ", chat_id=1, from_id=1)), Context())
        self.assertEqual(resp["statusCode"], 200)
        self.send.assert_not_called()
        self.start_async.assert_not_called()

    def test_starts_async_job_for_link(self):
        resp = bot.main(web_event(message("look https://youtu.be/dQw4w9WgXcQ?si=x")), Context())
        self.assertEqual(resp["statusCode"], 200)
        task = self.start_async.call_args.args[1]
        self.assertEqual(task, {"chat_id": OWNER, "url": "https://youtu.be/dQw4w9WgXcQ?si=x",
                                "status_id": 99, "reply_to": 10})
        self.run_job.assert_not_called()

    def test_falls_back_to_inline_job(self):
        self.start_async.side_effect = RuntimeError("no key")
        bot.main(web_event(message("https://youtu.be/dQw4w9WgXcQ")), Context())
        self.run_job.assert_called_once()

    def test_help_without_link(self):
        bot.main(web_event(message("/start")), Context())
        self.assertIn("YouTube link", self.send.call_args.args[1])
        self.start_async.assert_not_called()

    def test_errors_still_return_200(self):
        self.send.side_effect = Exception("telegram down")
        resp = bot.main(web_event(message("https://youtu.be/dQw4w9WgXcQ")), Context())
        self.assertEqual(resp["statusCode"], 200)

    def test_job_parameter_from_web_is_not_a_job(self):
        event = web_event(message("hi"))
        event["job"] = {"chat_id": 1, "url": "https://youtu.be/dQw4w9WgXcQ"}
        bot.main(event, Context())
        self.run_job.assert_not_called()


class StartAsyncTest(unittest.TestCase):
    def test_invokes_itself_non_blocking(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value.read.return_value = b'{"activationId": "a1"}'
        with mock.patch.object(bot.urllib.request, "urlopen", return_value=fake) as urlopen, \
                mock.patch.object(bot.json, "load", return_value={"activationId": "a1"}):
            bot.start_async(Context(), {"url": "u"})
        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url,
                         "https://faas-fra1-example.doserverless.co/api/v1/namespaces/fn-abc/actions/tg/bot?blocking=false")
        self.assertEqual(req.get_header("Authorization"), "Basic dXNlcjpwYXNz")


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
