#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"

if [ -x "$root/venv/Scripts/python.exe" ]; then
    python="$root/venv/Scripts/python.exe"
else
    python="${PYTHON:-python}"
fi

"$python" -m ruff check --isolated --select E4,E7,E9,F .
"$python" -m pytest -q
