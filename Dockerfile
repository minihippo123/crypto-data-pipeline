FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home appuser && mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["crypto-pipeline"]
