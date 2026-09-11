#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"
if [[ ! -x .venv/bin/python ]]; then
    printf '%s\n' 'Run ./scripts/setup.sh first.' >&2
    exit 1
fi
if [[ -n "${VITURE_SDK_LIBRARY:-}" ]]; then
    sdk_dir="$(dirname -- "$VITURE_SDK_LIBRARY")"
elif [[ -f "vendor/viture/$(uname -m)/libglasses.so" ]]; then
    sdk_dir="$project_dir/vendor/viture/$(uname -m)"
else
    sdk_dir=''
fi
if [[ -n "$sdk_dir" ]]; then
    export LD_LIBRARY_PATH="$sdk_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
exec .venv/bin/python -m spacewalker "$@"
