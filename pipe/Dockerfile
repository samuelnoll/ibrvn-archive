FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pipe/requirements.txt ./pipe/requirements.txt
RUN pip install --no-cache-dir -r pipe/requirements.txt

COPY pipe ./pipe
COPY shared ./shared

RUN mkdir -p /app/data/audio/raw /app/data/bronze /app/data/gold /app/logs/jobs

CMD ["sleep", "infinity"]
