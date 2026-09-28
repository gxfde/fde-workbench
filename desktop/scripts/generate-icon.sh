#!/bin/bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd -P)"
desktop_dir="$(cd "$script_dir/.." && pwd -P)"
build_dir="$desktop_dir/build"
iconset_dir="$(mktemp -d "${TMPDIR:-/tmp}/fde-workbench-icon.XXXXXX")/icon.iconset"

cleanup() {
  rm -rf "$(dirname "$iconset_dir")"
}
trap cleanup EXIT

mkdir -p "$iconset_dir"
base_png="$iconset_dir/icon_512x512@2x.png"
# Generate a transparent, rounded macOS icon before producing the ICNS. This
# keeps the installed icon rounded on older systems that do not apply a mask.
swift "$script_dir/render-macos-icon.swift" \
  "$desktop_dir/src/renderer/src/assets/logo.png" \
  "$build_dir/icon.png"
sips -s format png "$build_dir/icon.png" --out "$base_png" >/dev/null

render_size() {
  local pixels="$1"
  local filename="$2"
  sips -z "$pixels" "$pixels" "$base_png" --out "$iconset_dir/$filename" >/dev/null
}

render_size 16 icon_16x16.png
render_size 32 icon_16x16@2x.png
render_size 32 icon_32x32.png
render_size 64 icon_32x32@2x.png
render_size 128 icon_128x128.png
render_size 256 icon_128x128@2x.png
render_size 256 icon_256x256.png
render_size 512 icon_256x256@2x.png
render_size 512 icon_512x512.png

iconutil -c icns "$iconset_dir" -o "$build_dir/icon.icns"
