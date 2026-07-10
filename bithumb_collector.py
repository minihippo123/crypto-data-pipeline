import logging
import os
import time
from datetime import datetime

import pymysql
from dotenv import load_dotenv

from bithumb.candle_client import BithumbCandleClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_environment():
    for filename in ('.env', 'dbconfig.env'):
        env_path = os.path.join(SCRIPT_DIR, filename)
        if os.path.exists(env_path):
            load_dotenv(env_path, override=False)


def env_list(name, default):
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(',') if item.strip()]


class BithumbDataCollector:
    def __init__(self):
        load_environment()
        self.symbols = env_list('BITHUMB_SYMBOLS', ['BTC', 'ETH', 'XRP', 'SOL', 'SUI'])
        self.intervals = env_list('DQ_BITHUMB_INTERVALS', ['1m', '3m', '5m', '10m', '15m', '30m'])
        self.loop_sleep = float(os.getenv('RT_LOOP_SLEEP', '0.2'))
        self.error_sleep = float(os.getenv('BITHUMB_ERROR_SLEEP_SEC', '5'))
        self.candle_tasks_per_loop = int(os.getenv('CANDLE_TASKS_PER_LOOP', '3'))
        self.db_config = {
            'host': os.getenv('DB_HOST'),
            'port': int(os.getenv('DB_PORT', '3306')),
            'user': os.getenv('DB_USER'),
            'password': os.getenv('DB_PASSWORD'),
            'database': os.getenv('DB_NAME'),
        }
        self.client = BithumbCandleClient(
            base_url=os.getenv('BITHUMB_V1_API_BASE_URL', 'https://api.bithumb.com/v1'),
            timeout_sec=float(os.getenv('BITHUMB_CANDLE_TIMEOUT_SEC', '10')),
            max_retries=int(os.getenv('BITHUMB_CANDLE_MAX_RETRIES', '3')),
            retry_delay_sec=float(os.getenv('BITHUMB_CANDLE_RETRY_DELAY_SEC', '5')),
        )
        self.connect_db()
        self._last_heartbeat_log = 0
        logger.info('BithumbDataCollector 초기화 완료')

    def connect_db(self):
        self.db = pymysql.connect(**self.db_config)
        self.cursor = self.db.cursor()
        logger.info('데이터베이스 연결 성공')

    def _check_db_connection(self):
        try:
            self.db.ping(reconnect=True)
        except Exception:
            self.connect_db()

    def save_candles(self, symbol: str, interval: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        table = f'bithumb_{symbol.lower()}_candles'
        query = f"""
            INSERT IGNORE INTO {table}
            (`interval`, `open`, `high`, `low`, `close`, `volume`, `timestamp`)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        values = [
            (interval, row['open'], row['high'], row['low'], row['close'], row['volume'], row['timestamp'])
            for row in rows
        ]
        self.cursor.executemany(query, values)
        self.db.commit()
        return len(values)

    def collect_candles(self):
        processed = 0
        for symbol in self.symbols:
            for interval in self.intervals:
                rows = self.client.fetch_recent(symbol, interval, 200)
                written = self.save_candles(symbol, interval, rows)
                logger.info('bithumb %s %s candles=%s', symbol, interval, written)
                processed += 1
                time.sleep(self.loop_sleep)
                if processed >= self.candle_tasks_per_loop:
                    return

    def run(self):
        while True:
            try:
                self.collect_candles()
                now = time.time()
                if now - self._last_heartbeat_log >= 300:
                    logger.info('BithumbDataCollector 실행 중')
                    self._last_heartbeat_log = now
            except Exception as exc:
                logger.exception('Bithumb collection failed: %s', exc)
                self.db.rollback()
                self._check_db_connection()
                time.sleep(self.error_sleep)
            time.sleep(self.loop_sleep)

    def close(self):
        self.cursor.close()
        self.db.close()


if __name__ == '__main__':
    collector = BithumbDataCollector()
    try:
        collector.run()
    except KeyboardInterrupt:
        logger.info('프로그램 종료 요청')
    finally:
        collector.close()
