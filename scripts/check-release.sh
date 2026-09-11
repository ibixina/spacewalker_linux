#!/usr/bin/env bash
# Provider-neutral release gate. Run from a source checkout or extracted sdist.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
runtime="${SPACEWALKER_PYTHON:-$project_dir/.venv/bin/python}"
builder="${SPACEWALKER_BUILD_PYTHON:-$runtime}"
"$runtime" -m pytest -q
node --experimental-default-type=module --test tests/browser_view.mjs
env SPACEWALKER_GUI_TESTS=1 QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 \
    xvfb-run -a -s '-screen 0 1440x900x24' "$runtime" -m pytest tests/test_gui.py -q
"$builder" -m ruff check spacewalker tests scripts
bash -n run.sh scripts/setup.sh scripts/install-app.sh scripts/check-release.sh
"$builder" -m build
"$builder" -m twine check --strict dist/*.whl dist/*.tar.gz
"$builder" scripts/verify-dist.py dist
printf '%s\n' 'Local release gate passed. See RELEASE.md for native hardware acceptance and clean-install checks.'
