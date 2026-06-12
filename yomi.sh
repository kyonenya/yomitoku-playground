#!/bin/sh
set -eu

usage="Usage: $0 scan_dir [--dpi DPI] [--chunk CHUNK]"

scan_dir=${1:?"$usage"}
shift

input_dir="$scan_dir/out"
if [ ! -d "$input_dir" ]; then
  echo "input TIFF directory not found: $input_dir" >&2
  exit 1
fi

output_dir="$scan_dir/yomitoku"
output_name="$(basename "$scan_dir").pdf"
set -- "$input_dir" --output "$output_dir/$output_name" "$@"

uv run yomi.py "$@"
