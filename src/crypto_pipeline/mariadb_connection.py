from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def create_mariadb_engine() -> Engine:
    dsn = os.environ["MARIADB_DSN"]
    if not dsn.startswith(("mariadb+pymysql://", "mysql+pymysql://")):
        raise RuntimeError("MARIADB_DSN must use mariadb+pymysql:// or mysql+pymysql://")
    return create_engine(
        dsn,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
    )
