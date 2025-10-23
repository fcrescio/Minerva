# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS runtime

ARG SUPERCRONIC_VERSION=0.2.29

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /usr/local/bin/supercronic \
    "https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
    && chmod +x /usr/local/bin/supercronic

# Install runtime dependencies
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

COPY docker/prompts /usr/local/share/minerva/prompts
COPY docker/minerva-run.sh /usr/local/bin/minerva-run
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/minerva-run

ENV MINERVA_DATA_DIR=/data

VOLUME ["/data"]

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
