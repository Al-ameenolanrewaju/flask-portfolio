import os
import sys
from dotenv import load_dotenv

load_dotenv()

from mobile_alert_service import send_telegram_alert

bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
chat_id = os.environ.get('TELEGRAM_CHAT_ID')

if not bot_token or not chat_id:
    print('ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing in .env')
    sys.exit(1)

print(f'Sending test alert via Telegram bot to chat {chat_id}...')
success = send_telegram_alert(
    bot_token=bot_token,
    chat_id=chat_id,
    name='Recruiter Jane Doe',
    email='recruiter@techventures.io',
    subject='[Hiring] Senior Python / Backend Lead Opportunity',
    message='Hi Al-ameen, we reviewed your GitHub projects and architectural case studies. We would love to discuss a Senior Backend role with our team.',
    priority='high',
    triage_label='recruiter',
    reply_draft='Hi Jane, thank you for reaching out! I would love to connect and discuss the Senior Backend role. Feel free to book a 15-minute slot on my calendar or let me know what times work for you.'
)

if success:
    print('SUCCESS: Telegram notification received on your device!')
else:
    print('FAILED: Telegram API rejected the request. Please verify your bot token and chat ID.')

