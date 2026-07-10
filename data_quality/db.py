from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Any

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor
from dotenv import load_dotenv


load_dotenv()


class Database:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.dialect = "mysql"

    @classmethod
    def from_env(cls) -> "Database":
        connection = pymysql.connect(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            charset="utf8mb4",
            autocommit=False,
            cursorclass=DictCursor,
            connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT_SEC", "10")),
        )
        return cls(connection)

    @contextmanager
    def session(self) -> Iterator[Connection]:
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def execute(self, sql: str, params: tuple | list | None = None) -> int:
        with self.session() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params or ())
                return int(cursor.rowcount or 0)

    def executemany(self, sql: str, rows: list[tuple]) -> int:
        with self.session() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(sql, rows)
                return int(cursor.rowcount or 0)

    def fetchone(self, sql: str, params: tuple | list | None = None) -> dict | None:
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.fetchone()

    def fetchall(self, sql: str, params: tuple | list | None = None) -> list[dict]:
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params or ())
            return list(cursor.fetchall())

    def table_exists(self, name: str) -> bool:
        row = self.fetchone(
            "SELECT COUNT(*) AS cnt FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
            (os.getenv("DB_NAME"), name),
        )
        return bool(row and int(row["cnt"]) > 0)

    def close(self) -> None:
        self.connection.close()
