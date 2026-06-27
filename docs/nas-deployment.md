# NAS deployment

## 1. Prepare the directory

```bash
mkdir -p /volume1/docker/crypto-data-pipeline/data
cd /volume1/docker/crypto-data-pipeline
```

## 2. Clone and configure

```bash
git clone https://github.com/minihippo123/crypto-data-pipeline.git .
cp .env.example .env
```

Set the persistent NAS path in `.env`:

```dotenv
DATABASE_URL=sqlite:////app/data/crypto_pipeline.db
NAS_DATA_DIR=/volume1/docker/crypto-data-pipeline/data
```

The database path is the path seen inside the container. `NAS_DATA_DIR` is the real Synology host path mounted to `/app/data`.

## 3. Validate configuration

```bash
docker compose config --quiet
```

## 4. Build and run collectors

```bash
docker compose build bithumb-collector binance-collector
docker compose up -d bithumb-collector binance-collector
```

## 5. Verify containers and logs

```bash
docker compose ps
docker compose logs --tail 100 bithumb-collector
docker compose logs --tail 100 binance-collector
```

## 6. Run the quality demonstration

```bash
docker compose --profile demo run --rm quality-demo
```

## 7. Run the configured quality scan

```bash
docker compose --profile quality run --rm quality-pipeline
```

The Compose file reads `DATABASE_URL`, `NAS_DATA_DIR`, `QUALITY_SYMBOL`, `QUALITY_INTERVAL`, and source settings from `.env`. It no longer overrides the database URL with a hard-coded value.
