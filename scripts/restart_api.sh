#!/bin/bash

PROJECT_DIR="/opt/sermon-platform"
PID_FILE="$PROJECT_DIR/api.pid"
LOG_FILE="$PROJECT_DIR/logs/api/api.log"

cd $PROJECT_DIR

echo "--------------------------------------"
echo "API restart started $(date)"
echo "--------------------------------------"

# atualizar código
git pull origin main

# parar API se estiver rodando
if [ -f "$PID_FILE" ]; then
    PID=$(cat $PID_FILE)

    if ps -p $PID > /dev/null 2>&1; then
        echo "Stopping API process $PID"
        kill $PID
        sleep 3
    fi

    rm -f $PID_FILE
fi

# iniciar API
echo "Starting API..."
mkdir -p logs/api
cd $PROJECT_DIR
source venv/bin/activate
nohup uvicorn api.main:app --host 0.0.0.0 --port 8000 \
> $LOG_FILE 2>&1 &

# salvar PID
echo $! > $PID_FILE

echo "API started with PID $(cat $PID_FILE)"

echo "--------------------------------------"