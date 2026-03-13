#!/bin/bash

PROJECT_DIR="/opt/sermon-platform"

cd $PROJECT_DIR

echo "Starting YouTube weekly job..."

source venv/bin/activate

make job-youtube-weekly

echo "YouTube weekly job finished."