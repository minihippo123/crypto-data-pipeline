# Sync scope

This branch must align the public repository with `CryptoDB/Production` public runtime.

Allowed source files:

- `binance.py`
- `bithumb_collector.py`
- `bithumb/`
- `data_quality/`
- `notifications/`
- `tools/`
- `tests/`
- `Dockerfile`
- `Dockerfile.data-quality`
- `docker-compose.yml`
- `requirements.txt`
- `.env.example`
- `.gitignore`
- `.dockerignore`

Excluded files and content:

- `.env`
- `dbconfig.env`
- `apikey.env`
- actual API keys
- actual database host, password, or NAS path
- logs
- database dumps
- SQLite demo implementation
- `src/crypto_pipeline` toy implementation
- `app/` rewrite implementation
- account balance data

Rules:

- Do not create a new runtime architecture.
- Do not introduce SQLite fallback.
- Keep MariaDB environment contract: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`.
- Account collection is not part of the default public runtime.
- The PR is mergeable only after MariaDB integration validation passes.
