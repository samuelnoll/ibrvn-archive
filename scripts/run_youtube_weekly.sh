#!/bin/bash

set -euo pipefail

PROJECT_DIR="/opt/sermon-platform"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"

cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"

echo "Starting YouTube weekly job..."

"$PYTHON_BIN" -m jobs.youtube_job --mode weekly

echo "YouTube weekly job finished."
