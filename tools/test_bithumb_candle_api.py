from bithumb.candle_client import BithumbCandleClient


def main():
    client = BithumbCandleClient()
    rows = client.fetch_recent("BTC", "1m", 3)
    print(rows)


if __name__ == "__main__":
    main()
