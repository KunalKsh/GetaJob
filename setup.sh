#!/usr/bin/env bash
# macOS / Linux setup
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Setup complete. Run ./run.sh"
