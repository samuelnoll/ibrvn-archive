#!/bin/bash

PROJECT_DIR="/opt/sermon-platform"

cd $PROJECT_DIR

echo "Starting YouTube weekly job..."

source venv/bin/activate

python jobs/youtube_job.py weekly >> logs/jobs/youtube_weekly_cron.log 2>&1

echo "YouTube weekly job finished."