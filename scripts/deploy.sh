#!/bin/bash

cd /opt/sermon-platform

git pull origin master

source venv/bin/activate

make pipeline

