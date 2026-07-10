from __future__ import annotations

import os
import time
import requests

from .base import NotificationMessage, NotificationProvider


class TelegramProvider(NotificationProvider):
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.thread_id = os.getenv("TELEGRAM_MESSAGE_THREAD_ID")
        self.timeout = float(os.getenv("TELEGRAM_TIMEOUT_SEC", "8"))
        self.retries = int(os.getenv("TELEGRAM_RETRIES", "3"))
        self.parse_mode = os.getenv("TELEGRAM_PARSE_MODE", "HTML") or None

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, message: NotificationMessage) -> None:
        if not self.enabled:
            return
        payload = {
            "chat_id": self.chat_id,
            "text": f"{message.title}\n\n{message.body}",
            "disable_web_page_preview": True,
        }
        if self.thread_id:
            payload["message_thread_id"] = self.thread_id
        if self.parse_mode:
            payload["parse_mode"] = self.parse_mode
        last_error = None
        for attempt in range(1, self.retries + 1):
            try:
                response = requests.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(attempt)
        raise RuntimeError(f"Telegram notification failed: {last_error}")
