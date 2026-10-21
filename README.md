# tg-yt-bot

Telegram bot ([@rooxie_youtube_download_bot](https://t.me/rooxie_youtube_download_bot)): send it a YouTube link, get the audio back.
It runs as a DigitalOcean Function, deployed with Terraform as an App Platform app in project `9a0395e2-1f89-45c4-a3b3-1e1a14a6c909`.
It only works for Telegram account `168370115` (`ALLOWED_CHAT_IDS` in `functions/packages/tg/bot/__main__.py`; add IDs there to allow more people).

## How it works

```
Telegram ──webhook──▶ tg/bot                      checks secret header + chat ID,
                        │                          posts "⏳ Starting…", returns 200 at once
                        └─POST job, hang up ─────▶ tg/bot (job call, X-Bot-Job-Secret)
                          after 2 s                  yt-dlp → m4a in /tmp → sendAudio,
                                                     editing the status message as it goes
```

- **One function, two kinds of call.** Telegram's call carries its secret header. The webhook then sends the download job to the same function's web URL with a second secret header and hangs up after 2 seconds. Functions keeps running an invocation after the caller disconnects, up to the 15-minute limit, so Telegram gets its answer immediately and never resends. (App Platform forbids giving a function an API key, so the Functions API's own async invocation isn't available.) If the hand-off fails, the download runs inside the webhook call instead.
- **No ffmpeg or Node.** The Python runtime has neither, so nothing is converted. yt-dlp picks the best m4a under 50 MB (Telegram's upload limit for bots), usually AAC at about 130 kbps. Long videos fall back to YouTube's ~48 kbps m4a. YouTube's JavaScript challenges are solved with a bundled static [QuickJS](https://github.com/quickjs-ng/quickjs) binary, which `build.sh` downloads and checks against a pinned SHA-256.
- **Cost.** Functions bill per GiB-second, with 90,000 GiB-s free each month and no per-request or idle cost. A song takes about 8 s at 1 GB, so roughly 10,000 songs a month are free.

## Deploy

1. **Start the bot.** Open [@rooxie_youtube_download_bot](https://t.me/rooxie_youtube_download_bot) and press **Start**. Bots can't message you first.
2. **Push this folder to a public GitHub repo.** App Platform builds function code only from a Git repo, and a public one needs no GitHub authorization:
   ```sh
   git init -b main && git add . && git commit -m "tg-yt-bot"
   gh repo create tg-yt-bot --public --source . --push
   ```
   Both secrets stay out of git: the bot token goes in `terraform.tfvars` and the DigitalOcean token in `digitalocean.key`, and both are gitignored.
3. **Deploy:**
   ```sh
   cp terraform.tfvars.example terraform.tfvars   # set github_repo and telegram_bot_token
   # put a DigitalOcean API token (read/write) in digitalocean.key
   terraform init
   terraform apply
   ```
   This creates the app, waits for the first build and deploy, then registers the webhook with Telegram.
4. **Try it.** Send the bot a YouTube link.

The app clones the public repo, so pushing doesn't redeploy by itself. To deploy the latest `main`, which also installs the newest yt-dlp (the usual fix when YouTube downloads start failing):

```sh
APP=$(terraform output -raw app_id)
curl -s -X POST -H "Authorization: Bearer $(cat digitalocean.key)" -H "Content-Type: application/json" \
  -d '{"force_build": true}' "https://api.digitalocean.com/v2/apps/$APP/deployments"
```

For automatic deploys on every push, authorize DigitalOcean's GitHub app for the repo (*App Platform → Create App → GitHub*), then change the `git` block in `main.tf` to `github { repo = var.github_repo, branch = var.github_branch, deploy_on_push = true }`.

## Troubleshooting

- **Telegram's side:** `curl -s "https://api.telegram.org/bot<token>/getWebhookInfo"` shows the URL, the number of pending updates and the last delivery error.
- **Function logs:** go to *App Platform → tg-yt-bot → Runtime Logs*. `started download of … via …` means the hand-off worked. `job hand-off failed … running inline` means it didn't: downloads still work, but a slow one can make Telegram resend the update and start a duplicate.
- **"Sign in to confirm you're not a bot":** YouTube distrusts the datacenter IP. Redeploy first (newer yt-dlp). If it persists, this host is blocked, and the options are cookies from a throwaway account or a residential proxy.

## Tests

```sh
python3 -m unittest discover -s tests
```

They cover the webhook checks, ignoring other users, the async hand-off and its inline fallback, and link detection. They stub out Telegram and yt-dlp, so no dependencies or network are needed.

## Layout

```
main.tf, variables.tf, outputs.tf, versions.tf   App Platform app, webhook secret, Telegram webhook
functions/project.yml                            function config: runtime, 15 min / 1 GB limits, env
functions/packages/tg/bot/__main__.py            entry point: webhook checks and async hand-off
functions/packages/tg/bot/job.py                 download, status updates, upload
functions/packages/tg/bot/telegram.py            Telegram Bot API calls
functions/packages/tg/bot/build.sh               remote build: deps + QuickJS
tests/                                           unit tests
```
