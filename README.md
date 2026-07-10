# Crypto Data Pipeline

MariaDB-backed cryptocurrency market-data collectors and an auditable Data Quality Manager.

This public repository is aligned to the public-runtime subset of `CryptoDB/Production`:

- Binance public market collector
- Bithumb public market collector
- Bithumb candle API client
- Data Quality Manager
- notification formatting/adapters
- operational Docker Compose runtime

Private account collection, real credentials, private NAS paths, logs, database snapshots, and local deployment files are excluded.

## Configure

```bash
cp .env.example .env
```

Set MariaDB values:

```dotenv
DB_HOST=your-db-host
DB_PORT=3306
DB_USER=your-db-user
DB_PASSWORD=change-me
DB_NAME=CryptoDB
```

## Run collectors

```bash
docker compose config --quiet
docker compose up -d --build binance-collector bithumb-collector
```

## Run Data Quality Manager

```bash
docker compose run --rm data-quality-manager --mode auto
```

## Important boundary

Do not add SQLite demo code, `app/` rewrites, synthetic-only pipelines, credentials, account balances, order/position data, logs, DB dumps, or machine-specific NAS paths.
