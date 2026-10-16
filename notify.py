"""Telegram-ilmoitukset. Ei koskaan nosta poikkeusta eika tulosta tokenia."""
import json
import urllib.parse
import urllib.request


def laheta(teksti, env, hae=None):
    """Palauttaa True/False. env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID."""
    tok, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": teksti[:3500]}).encode()
    try:
        if hae:
            return bool(hae(tok, chat, teksti[:3500]))
        with urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, data=data, timeout=20) as v:
            return json.loads(v.read().decode()).get("ok") is True
    except Exception:
        return False
