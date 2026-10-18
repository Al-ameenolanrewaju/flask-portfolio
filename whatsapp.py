from external_http import request_with_retries


class WhatsAppProvider:
    def send_message(self, message):
        raise NotImplementedError


class CallMeBotProvider(WhatsAppProvider):
    ENDPOINT = 'https://api.callmebot.com/whatsapp.php'

    def __init__(self, phone, api_key):
        self.phone = phone
        self.api_key = api_key

    def send_message(self, message):
        response = request_with_retries(
            'GET',
            self.ENDPOINT,
            params={'phone': self.phone, 'text': message, 'apikey': self.api_key},
            timeout=(3.05, 10),
        )
        response.raise_for_status()
        return True