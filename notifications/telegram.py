from __future__ import annotations

import os
import requests

from .base import NotificationMessage, NotificationProvider


class TelegramProvider(NotificationProvider):
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.timeout = float(os.getenv("TELEGRAM_TIMEOUT_SEC", "8"))

    def send(self, message: NotificationMessage) -> None:
        if not self.token or not self.chat_id:
            return
        requests.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": self.chat_id, "text": f"{message.title}\n\n{message.body}"},
            timeout=self.timeout,
        )
