#!/bin/bash

cd ~/SDRCC || exit 1

source venv/bin/activate

clear
echo "========================================="
echo "     SDRCC Mission Control"
echo "========================================="
echo

python3 dashboard/app.py
