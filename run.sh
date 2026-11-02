#!/usr/bin/env bash
cd "$(dirname "$0")"
(sleep 2; open http://127.0.0.1:8000 2>/dev/null || xdg-open http://127.0.0.1:8000 2>/dev/null) &
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
