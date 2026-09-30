#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f ".venv/bin/python" ]; then
    exec ".venv/bin/python" -m geox.cli "$@"
elif [ -f "runtime/bin/python" ]; then
    exec "runtime/bin/python" -m geox.cli "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 -m geox.cli "$@"
elif command -v python >/dev/null 2>&1; then
    exec python -m geox.cli "$@"
else
    echo "No Python runtime found. Run ./run_geox.sh first."
    exit 1
fi
