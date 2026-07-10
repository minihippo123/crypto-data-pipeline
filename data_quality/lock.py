from __future__ import annotations

from datetime import datetime, timedelta


class DataQualityLock:
    def __init__(self, db, name: str, owner: str, timeout_minutes: int = 120):
        self.db = db
        self.name = name
        self.owner = owner
        self.timeout_minutes = timeout_minutes

    def acquire(self) -> bool:
        now = datetime.now()
        expires = now + timedelta(minutes=self.timeout_minutes)
        self.db.execute(
            "DELETE FROM dq_locks WHERE lock_name=%s AND expires_at < %s",
            (self.name, now),
        )
        try:
            self.db.execute(
                "INSERT INTO dq_locks (lock_name, owner, acquired_at, expires_at) VALUES (%s,%s,%s,%s)",
                (self.name, self.owner, now, expires),
            )
            return True
        except Exception:
            return False

    def release(self) -> None:
        self.db.execute("DELETE FROM dq_locks WHERE lock_name=%s AND owner=%s", (self.name, self.owner))
