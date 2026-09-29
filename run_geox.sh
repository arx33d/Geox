#!/usr/bin/env bash
# Geox launcher (macOS / Linux / Git Bash)
cd "$(dirname "$0")"

if [ ! -f .venv/bin/python ] && [ ! -f .venv/Scripts/python.exe ]; then
  echo "First run - setting up Python environment..."
  python3 -m venv .venv
fi

PY=.venv/bin/python
[ -f "$PY" ] || PY=.venv/Scripts/python.exe

"$PY" -m pip install --quiet -r requirements.txt
exec "$PY" -m geox.server
