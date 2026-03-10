#!/bin/bash

cd /opt/sermon-platform

git pull

source venv/bin/activate

make pipeline

