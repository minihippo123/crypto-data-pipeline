FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY binance.py bithumb_collector.py ./
COPY bithumb ./bithumb
COPY data_quality ./data_quality
COPY notifications ./notifications
COPY tools ./tools

RUN mkdir -p /app/logs

CMD ["python", "bithumb_collector.py"]
