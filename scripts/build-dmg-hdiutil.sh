#!/bin/bash
# Build the ARM64 .app with electron-builder (dir target, no DMG) then create the
# DMG with hdiutil directly.
#
# Why: electron-builder's bundled dmgbuild runs `hdiutil ... -plist` and feeds the
# whole stdout to plistlib.loads. When hdiutil emits warnings, they are prepended
# to the plist document and plistlib.loads raises "Invalid file" (dmgbuild #197).
# Creating the DMG with hdiutil directly bypasses that broken parser.
#
# Usage (from apps/fde-workbench):
#   bash scripts/build-dmg-hdiutil.sh
# Prereq: a local Flask API may be running at 127.0.0.1:8010 (the app points to it),
#         but it is not required to package.
set -euo pipefail

app_root="$(cd "$(dirname "$0")/.." && pwd -P)"
release_dir="$app_root/release"
app_name="FDE 工作台.app"
app_path="$release_dir/mac-arm64/$app_name"
version="$(node -p "require('$app_root/desktop/package.json').version")"
dmg_path="$release_dir/FDE-Workbench-${version}-arm64.dmg"

echo "==> Building ARM64 .app (dir target, no dmgbuild)"
(
  cd "$app_root/desktop"
  npm run build
  npm run icon:mac
  npx electron-builder --mac dir --arm64
)

if [[ ! -d "$app_path" ]]; then
  echo "ERROR: packaged app not found at $app_path" >&2
  exit 1
fi

echo "==> Creating DMG with hdiutil"
stage="$(mktemp -d "${TMPDIR:-/tmp}/fde-dmg-stage.XXXXXX")"
cleanup() { rm -rf "$stage"; }
trap cleanup EXIT
cp -R "$app_path" "$stage/"

rm -f "$dmg_path"
hdiutil create -volname "FDE 工作台" -srcfolder "$stage" -ov -format UDZO "$dmg_path"

echo "==> DMG created: $dmg_path"
echo "    Verify with: bash scripts/verify-dmg.sh"
