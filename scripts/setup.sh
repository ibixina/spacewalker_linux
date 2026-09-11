#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
printf '%s\n' 'Ready. Start with ./run.sh. Run ./run.sh --doctor to check the system.'
