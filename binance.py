import os
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional

import requests
import pymysql
from dotenv import load_dotenv


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


class BinanceDataCollector:
    def __init__(self):
        load_environment()
        self.base_url = os.getenv('BINANCE_BASE_URL', 'https://api.binance.com/api/v3').rstrip('/')
        self.symbols = env_list('BINANCE_SYMBOLS', ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'SUIUSDT', 'SOLUSDT'])
        self.intervals = env_list('BINANCE_INTERVALS', ['1m', '3m', '5m', '15m', '30m', '1h'])
        self.update_interval = float(os.getenv('BINANCE_UPDATE_INTERVAL_SEC', '0.1'))
        self.api_call_sleep_sec = float(os.getenv('BINANCE_API_CALL_SLEEP_SEC', '0.1'))
        self.symbol_sleep_sec = float(os.getenv('BINANCE_SYMBOL_SLEEP_SEC', '0.5'))
        self.trades_limit = int(os.getenv('BINANCE_TRADES_LIMIT', '1000'))
        self.klines_limit = int(os.getenv('BINANCE_KLINES_LIMIT', '1000'))
        self.orderbook_limit = int(os.getenv('BINANCE_ORDERBOOK_LIMIT', '100'))
        self.db_config = {
            'host': os.getenv('DB_HOST'),
            'port': int(os.getenv('DB_PORT', '3306')),
            'user': os.getenv('DB_USER'),
            'password': os.getenv('DB_PASSWORD'),
            'database': os.getenv('DB_NAME'),
        }
        self.connect_db()
        self.last_timestamps = {
            symbol: {'trades': None, 'orderbook': None, 'candles': {interval: None for interval in self.intervals}}
            for symbol in self.symbols
        }
        self._last_heartbeat_log = 0
        logger.info('BinanceDataCollector 초기화 완료')

    def connect_db(self):
        self.db = pymysql.connect(**self.db_config)
        self.cursor = self.db.cursor()
        logger.info('데이터베이스 연결 성공')

    def _check_db_connection(self):
        try:
            self.db.ping(reconnect=True)
        except Exception:
            self.connect_db()

    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        try:
            response = requests.get(f'{self.base_url}{endpoint}', params=params, timeout=10)
            if response.status_code == 429:
                time.sleep(int(response.headers.get('Retry-After', 5)))
                return None
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            logger.error('API 요청 실패: %s', exc)
            return None

    def check_duplicate(self, symbol: str, data_type: str, timestamp: datetime, interval: str = None) -> bool:
        last_time = self.last_timestamps[symbol][data_type]
        if interval:
            last_time = last_time[interval]
        if last_time and timestamp <= last_time:
            return True
        if interval:
            self.last_timestamps[symbol][data_type][interval] = timestamp
        else:
            self.last_timestamps[symbol][data_type] = timestamp
        return False

    def fetch_trades(self, symbol: str, limit: int = 1000) -> List[Dict]:
        data = self._make_request('/trades', {'symbol': symbol, 'limit': limit})
        if not data:
            return []
        rows = []
        for trade in data:
            timestamp = datetime.fromtimestamp(trade['time'] / 1000)
            if not self.check_duplicate(symbol, 'trades', timestamp):
                rows.append(trade)
        return rows

    def fetch_klines(self, symbol: str, interval: str, limit: int = 1000) -> List[List]:
        data = self._make_request('/klines', {'symbol': symbol, 'interval': interval, 'limit': limit})
        return data if isinstance(data, list) else []

    def fetch_orderbook(self, symbol: str) -> Optional[Dict]:
        data = self._make_request('/depth', {'symbol': symbol, 'limit': self.orderbook_limit})
        if not data or not all(key in data for key in ('bids', 'asks')):
            return None
        return {
            'bids': [{'price': float(bid[0]), 'quantity': float(bid[1])} for bid in data['bids']],
            'asks': [{'price': float(ask[0]), 'quantity': float(ask[1])} for ask in data['asks']],
        }

    def save_trades(self, symbol: str, trades: List[Dict]):
        if not trades:
            return
        table_symbol = symbol.lower().replace('usdt', '')
        query = f"""
            INSERT IGNORE INTO binance_{table_symbol}_trades
            (price, volume, is_buyer_maker, timestamp)
            VALUES (%s, %s, %s, FROM_UNIXTIME(%s/1000))
        """
        values = [(trade['price'], trade['qty'], 1 if trade['isBuyerMaker'] else 0, trade['time']) for trade in trades]
        self.cursor.executemany(query, values)
        self.db.commit()

    def save_candles(self, symbol: str, candles: List[List], interval: str):
        if not candles:
            return
        table_symbol = symbol.lower().replace('usdt', '')
        query = f"""
            INSERT IGNORE INTO binance_{table_symbol}_candles
            (`interval`, `open`, `high`, `low`, `close`, `volume`, `timestamp`)
            VALUES (%s, %s, %s, %s, %s, %s, FROM_UNIXTIME(%s/1000))
        """
        values = [(interval, candle[1], candle[2], candle[3], candle[4], candle[5], candle[0]) for candle in candles]
        self.cursor.executemany(query, values)
        self.db.commit()

    def save_orderbook(self, symbol: str, orderbook: Dict):
        if not orderbook:
            return
        table_symbol = symbol.lower().replace('usdt', '')
        table_name = f'binance_{table_symbol}_orderbooks'
        best_bid = orderbook['bids'][0]
        best_ask = orderbook['asks'][0]
        bid_total_volume = sum(row['quantity'] for row in orderbook['bids'][:5])
        ask_total_volume = sum(row['quantity'] for row in orderbook['asks'][:5])
        book_imbalance = bid_total_volume / ask_total_volume if ask_total_volume > 0 else 0
        sql = f"""
            INSERT INTO {table_name}
            (timestamp, bid_price, bid_volume, ask_price, ask_volume, bid_total_volume, ask_total_volume, spread, book_imbalance)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        self.cursor.execute(sql, (
            datetime.now(), best_bid['price'], best_bid['quantity'], best_ask['price'], best_ask['quantity'],
            bid_total_volume, ask_total_volume, best_ask['price'] - best_bid['price'], book_imbalance,
        ))
        self.db.commit()

    def collect_and_save_data(self):
        for symbol in self.symbols:
            try:
                self.save_trades(symbol, self.fetch_trades(symbol, self.trades_limit))
                self.save_orderbook(symbol, self.fetch_orderbook(symbol))
                for interval in self.intervals:
                    self.save_candles(symbol, self.fetch_klines(symbol, interval, self.klines_limit), interval)
                    time.sleep(self.api_call_sleep_sec)
            except Exception as exc:
                logger.error('데이터 수집 중 오류 (%s): %s', symbol, exc)
                self.db.rollback()
                self._check_db_connection()
            time.sleep(self.symbol_sleep_sec)

    def run(self):
        while True:
            self.collect_and_save_data()
            now = time.time()
            if now - self._last_heartbeat_log >= 300:
                logger.info('BinanceDataCollector 실행 중')
                self._last_heartbeat_log = now
            time.sleep(self.update_interval)

    def close(self):
        self.cursor.close()
        self.db.close()


if __name__ == '__main__':
    collector = BinanceDataCollector()
    try:
        collector.run()
    except KeyboardInterrupt:
        logger.info('프로그램 종료 요청')
    finally:
        collector.close()
