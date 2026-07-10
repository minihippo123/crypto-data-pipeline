from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NotificationMessage:
    title: str
    body: str
    severity: str = "INFO"


class NotificationProvider:
    def send(self, message: NotificationMessage) -> None:
        raise NotImplementedError
