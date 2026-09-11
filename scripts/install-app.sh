#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
data_dir="${XDG_DATA_HOME:-${HOME}/.local/share}"
application_dir="${data_dir}/applications"
icon_dir="${data_dir}/icons/hicolor/scalable/apps"
desktop_file="${application_dir}/spacewalker-linux.desktop"
desktop_template="${project_dir}/packaging/spacewalker-linux.desktop.in"
runner="${project_dir}/run.sh"
temporary_desktop="$(mktemp --suffix=.desktop)"
trap 'rm -f -- "$temporary_desktop"' EXIT

if [[ ! -x "$runner" ]]; then
    printf 'Spacewalker launcher is not executable: %s\n' "$runner" >&2
    exit 1
fi

mkdir -p -- "$application_dir" "$icon_dir"
python3 "${project_dir}/scripts/render-desktop.py" "$desktop_template" "$runner" > "$temporary_desktop"
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$temporary_desktop"
fi
install -m 0644 "$temporary_desktop" "$desktop_file"
install -m 0644 "${project_dir}/packaging/spacewalker-linux.svg" \
    "${icon_dir}/spacewalker-linux.svg"

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$desktop_file"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$application_dir"
fi

printf 'Installed Spacewalker Linux in the application menu.\n'
