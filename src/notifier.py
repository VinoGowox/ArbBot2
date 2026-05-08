from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

from .config import BotConfig

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, config: BotConfig) -> None:
        self._token = config.telegram_bot_token
        self._chat_id = config.telegram_chat_id
        self.enabled = bool(self._token and self._chat_id)

    def send(self, message: str) -> bool:
        if not self.enabled:
            return False

        payload = urllib.parse.urlencode(
            {
                "chat_id": self._chat_id,
                "text": message,
            }
        ).encode("utf-8")
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"

        request = urllib.request.Request(url, data=payload, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                body = response.read().decode("utf-8", errors="ignore")
                data = json.loads(body)
                return bool(data.get("ok", False))
        except Exception as exc:
            logger.warning("Telegram send failed: %s", exc)
            return False
