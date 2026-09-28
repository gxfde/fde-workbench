#!/bin/bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd -P)"
app_root="$(cd "$script_dir/.." && pwd -P)"
expected_version="$(node -p "require('$app_root/desktop/package.json').version")"
dmg_path="${1:-$app_root/release/FDE-Workbench-${expected_version}-arm64.dmg}"
mount_dir="$(mktemp -d "${TMPDIR:-/tmp}/fde-workbench-dmg.XXXXXX")"
user_data_dir="$(mktemp -d "${TMPDIR:-/tmp}/fde-workbench-user-data.XXXXXX")"
launch_log="$(mktemp "${TMPDIR:-/tmp}/fde-workbench-launch.XXXXXX.log")"
mounted=0
app_pid=""

cleanup() {
  if [[ -n "$app_pid" ]] && kill -0 "$app_pid" 2>/dev/null; then
    kill "$app_pid" 2>/dev/null || true
    wait "$app_pid" 2>/dev/null || true
  fi
  pkill -TERM -f "$mount_dir/FDE 工作台.app" 2>/dev/null || true
  for _ in {1..20}; do
    if ! pgrep -f "$mount_dir/FDE 工作台.app" >/dev/null 2>&1; then
      break
    fi
    sleep 0.1
  done
  pkill -KILL -f "$mount_dir/FDE 工作台.app" 2>/dev/null || true
  if [[ "$mounted" -eq 1 ]]; then
    hdiutil detach "$mount_dir" -quiet 2>/dev/null ||
      hdiutil detach "$mount_dir" -force -quiet 2>/dev/null || true
  fi
  rm -rf "$mount_dir" "$user_data_dir" "$launch_log"
}
trap cleanup EXIT

if [[ ! -f "$dmg_path" ]]; then
  echo "DMG not found: $dmg_path" >&2
  exit 1
fi

hdiutil verify "$dmg_path" >/dev/null
hdiutil attach "$dmg_path" -readonly -nobrowse -mountpoint "$mount_dir" >/dev/null
mounted=1

app_path="$mount_dir/FDE 工作台.app"
plist_path="$app_path/Contents/Info.plist"
if [[ ! -d "$app_path" ]]; then
  echo "Application bundle missing from DMG." >&2
  exit 1
fi

bundle_id="$(plutil -extract CFBundleIdentifier raw -o - "$plist_path")"
version="$(plutil -extract CFBundleShortVersionString raw -o - "$plist_path")"
minimum_system="$(plutil -extract LSMinimumSystemVersion raw -o - "$plist_path")"
executable_name="$(plutil -extract CFBundleExecutable raw -o - "$plist_path")"
executable_path="$app_path/Contents/MacOS/$executable_name"
architectures="$(lipo -archs "$executable_path")"

[[ "$bundle_id" == "org.fdeworkbench.desktop" ]]
[[ "$version" == "$expected_version" ]]
[[ "$minimum_system" == "13.0.0" ]]
[[ " $architectures " == *" arm64 "* ]]
[[ " $architectures " != *" x86_64 "* ]]

codesign --verify --deep --strict --verbose=2 "$app_path"
codesign_details="$(codesign -dv --verbose=4 "$app_path" 2>&1)"
if grep -q "Authority=Developer ID Application:" <<<"$codesign_details"; then
  signature_kind="Developer ID Application"
  if [[ "${FDE_REQUIRE_NOTARIZED:-0}" == "1" ]]; then
    xcrun stapler validate "$app_path"
    xcrun stapler validate "$dmg_path"
    spctl --assess --type execute --verbose=2 "$app_path"
  fi
else
  grep -q "Signature=adhoc" <<<"$codesign_details"
  signature_kind="ad-hoc"
  if [[ "${FDE_REQUIRE_NOTARIZED:-0}" == "1" ]]; then
    echo "Notarized release required; ad-hoc signature found." >&2
    exit 1
  fi
fi

env -u FDE_DESKTOP_API_URL "$executable_path" \
  --user-data-dir="$user_data_dir" >"$launch_log" 2>&1 &
app_pid=$!

for _ in {1..20}; do
  if ! kill -0 "$app_pid" 2>/dev/null; then
    cat "$launch_log" >&2
    echo "Packaged application exited during launch verification." >&2
    exit 1
  fi
  sleep 0.1
done

sha256="$(shasum -a 256 "$dmg_path" | awk '{print $1}')"
echo "DMG: $dmg_path"
echo "Bundle ID: $bundle_id"
echo "Version: $version"
echo "Minimum macOS: $minimum_system"
echo "Architecture: $architectures"
echo "Signature: $signature_kind"
echo "Launch: passed without FDE_DESKTOP_API_URL environment variable"
echo "SHA-256: $sha256"
