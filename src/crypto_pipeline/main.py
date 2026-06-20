import argparse
import json

from .config import Settings
from .pipeline import DataQualityPipeline
from .repository import SQLiteRepository
from .source import HttpCandleSource


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the public crypto data pipeline")
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()

    settings = Settings.from_env()
    repository = SQLiteRepository(settings.database_url)
    source = None
    if args.repair:
        source = HttpCandleSource(
            settings.source_api_base_url,
            settings.source_api_timeout_seconds,
        )
    try:
        result = DataQualityPipeline(repository, source).run(
            args.symbol,
            args.interval,
            repair=args.repair,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        repository.close()


if __name__ == "__main__":
    main()
