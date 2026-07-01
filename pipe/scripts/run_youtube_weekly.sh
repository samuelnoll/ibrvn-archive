#!/bin/bash

set -euo pipefail

PROJECT_DIR="/opt/sermon-platform"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
ENV_FILE="$PROJECT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "Missing env file: $ENV_FILE"
    exit 1
fi

set -a
source "$ENV_FILE"
set +a

if [ -z "${YOUTUBE_API_KEY:-}" ]; then
    echo "Missing YOUTUBE_API_KEY in $ENV_FILE"
    exit 1
fi

cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"

echo "Starting YouTube weekly job..."

"$PYTHON_BIN" -m pipe.jobs.youtube_job --mode weekly

echo "YouTube weekly job finished."
