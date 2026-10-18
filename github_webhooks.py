import hashlib
import hmac
import re


def verify_github_signature(payload, signature, secret):
    if not secret or not signature or not re.fullmatch(r'sha256=[0-9a-f]{64}', signature):
        return False
    expected = 'sha256=' + hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)