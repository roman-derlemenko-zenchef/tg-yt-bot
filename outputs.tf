output "app_url" {
  description = "Live URL of the App Platform app."
  value       = digitalocean_app.bot.live_url
}

output "webhook_url" {
  description = "URL Telegram sends updates to."
  value       = local.webhook_url
}

output "check_webhook" {
  description = "Shows Telegram's view of the webhook, including the last delivery error."
  value       = "curl -s \"https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo\""
}
