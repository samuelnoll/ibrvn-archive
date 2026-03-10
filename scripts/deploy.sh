#!/bin/bash

cd /opt/sermon-platform

git pull origin main

source venv/bin/activate

make pipeline

