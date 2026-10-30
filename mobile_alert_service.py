import logging
import urllib.parse
import requests

from external_http import request_with_retries

logger = logging.getLogger('portfolio.mobile_alerts')


def format_quick_mailto(email, subject, reply_draft):
    safe_subject = urllib.parse.quote(f"Re: {subject or 'Your Inquiry'}")
    body_text = reply_draft if reply_draft else "Hi,\n\nThank you for reaching out to me!\n\nBest regards,\nAl-ameen"
    safe_body = urllib.parse.quote(body_text)
    return f"mailto:{email}?subject={safe_subject}&body={safe_body}"


def send_telegram_alert(bot_token, chat_id, name, email, subject, message, priority='normal', triage_label='other', reply_draft=None):
    if not bot_token or not chat_id:
        return False

    endpoint = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    mailto_link = format_quick_mailto(email, subject, reply_draft)

    priority_emoji = "🚨" if priority == "high" else "📩"
    label_tag = f"#{triage_label.upper()}" if triage_label else "#INQUIRY"

    draft_section = ""
    if reply_draft:
        draft_section = f"\n\n🤖 <b>AI Suggested Reply:</b>\n<i>{reply_draft[:400]}...</i>"

    text = (
        f"{priority_emoji} <b>New Portfolio Lead ({label_tag})</b>\n\n"
        f"👤 <b>From:</b> {name} (<code>{email}</code>)\n"
        f"🏷️ <b>Priority:</b> {priority.upper()}\n"
        f"📌 <b>Subject:</b> {subject}\n\n"
        f"💬 <b>Message:</b>\n<i>{message[:500]}</i>"
        f"{draft_section}\n\n"
        f"👉 <a href=\"{mailto_link}\">Tap here to 1-Click Reply via Email</a>"
    )

    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    }

    try:
        response = request_with_retries('POST', endpoint, json=payload, timeout=(3.05, 10), attempts=2)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.warning('Failed to send Telegram alert: %s', e)
        return False


def send_discord_alert(webhook_url, name, email, subject, message, priority='normal', triage_label='other', reply_draft=None):
    if not webhook_url:
        return False

    color = 0xef4444 if priority == 'high' else 0x10b981
    fields = [
        {'name': 'From', 'value': f"{name} ({email})", 'inline': True},
        {'name': 'Category', 'value': f"{triage_label.title()} ({priority.upper()})", 'inline': True},
        {'name': 'Subject', 'value': subject or 'No Subject', 'inline': False},
        {'name': 'Message', 'value': message[:800], 'inline': False},
    ]

    if reply_draft:
        fields.append({'name': 'AI Suggested Reply', 'value': reply_draft[:800], 'inline': False})

    mailto_link = format_quick_mailto(email, subject, reply_draft)
    fields.append({'name': 'Quick Action', 'value': f"[📱 1-Tap Reply via Mail Client]({mailto_link})", 'inline': False})

    payload = {
        'username': 'Portfolio Lead Alert',
        'embeds': [{
            'title': f"New Lead Received: {subject}",
            'color': color,
            'fields': fields,
        }]
    }

    try:
        response = request_with_retries('POST', webhook_url, json=payload, timeout=(3.05, 10), attempts=2)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.warning('Failed to send Discord alert: %s', e)
        return False


def dispatch_mobile_alerts(config, name, email, subject, message, priority='normal', triage_label='other', reply_draft=None):
    """Dispatch alerts to configured mobile webhooks (Telegram / Discord)."""
    dispatched = False

    tg_token = config.get('TELEGRAM_BOT_TOKEN')
    tg_chat = config.get('TELEGRAM_CHAT_ID')
    if tg_token and tg_chat:
        if send_telegram_alert(tg_token, tg_chat, name, email, subject, message, priority, triage_label, reply_draft):
            dispatched = True

    discord_url = config.get('DISCORD_WEBHOOK_URL')
    if discord_url:
        if send_discord_alert(discord_url, name, email, subject, message, priority, triage_label, reply_draft):
            dispatched = True

    return dispatched

