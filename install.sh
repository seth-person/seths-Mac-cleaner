#!/bin/bash
# Installs the Mac Cleaner app from the latest GitHub release, from Terminal.
#
#   ./install.sh               install, or reinstall the latest version
#   ./install.sh --uninstall   remove the app (settings and scans in ~/.macclean stay)
#
# The usual way to install is the .dmg on the Releases page. This script does the
# same thing, and skips macOS's "unidentified developer" warning because nothing
# is downloaded by a browser. After installing, updates happen inside the app.
set -euo pipefail

REPO="seth-person/seths-Mac-cleaner"
APP_NAME="Mac Cleaner.app"
SERVICE="Mac Cleaner GitHub"
SUPPORT="${MACCLEAN_INSTALL_ROOT:-$HOME/Library/Application Support/Mac Cleaner}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf '\nError: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

if [ -n "${MACCLEAN_APPS_DIR:-}" ]; then
  APPS="$MACCLEAN_APPS_DIR"
elif [ -w /Applications ]; then
  APPS=/Applications
else
  APPS="$HOME/Applications"
fi
APP="$APPS/$APP_NAME"

if [ "${1:-}" = "--uninstall" ]; then
  have osascript && osascript -e 'tell application id "com.seth-person.mac-cleaner" to quit' >/dev/null 2>&1 || true
  rm -rf "$APP" "$HOME/Applications/$APP_NAME" "$SUPPORT"
  have security && security delete-generic-password -s "$SERVICE" >/dev/null 2>&1 || true
  bold "Mac Cleaner removed. Your settings, scans and history are still in ~/.macclean."
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

json_get() {  # json_get <file> <js expression using r>; macOS has no Python by default
  osascript -l JavaScript -e 'function run(a){var r=JSON.parse(a[0]);return eval(a[1])}' "$(cat "$1")" "$2"
}

if [ -n "${MACCLEAN_APP_ZIP:-}" ]; then
  zip="$MACCLEAN_APP_ZIP"   # for testing: install from a local build
else
  token="${MACCLEAN_GITHUB_TOKEN:-}"
  if [ -z "$token" ] && have security; then
    token="$(security find-generic-password -s "$SERVICE" -w 2>/dev/null || true)"
  fi
  status="$(curl -s -o "$tmp/release.json" -w '%{http_code}' ${token:+-H "Authorization: Bearer $token"} \
           "https://api.github.com/repos/$REPO/releases/latest")"
  if [ "$status" != "200" ]; then
    bold "Mac Cleaner's repository is private, so this needs a GitHub token."
    cat <<'EOF'
  1. Open https://github.com/settings/personal-access-tokens/new
  2. Name it "Mac Cleaner". Under Repository access choose "Only select repositories"
     and pick seths-Mac-cleaner. Under Permissions give Contents: Read-only.
  3. Generate it and paste it below. It's stored in your Keychain, and the app uses it for updates.
EOF
    printf 'Token: '
    IFS= read -rs token </dev/tty
    echo
    status="$(curl -s -o "$tmp/release.json" -w '%{http_code}' -H "Authorization: Bearer $token" \
             "https://api.github.com/repos/$REPO/releases/latest")"
    [ "$status" = "200" ] || die "GitHub didn't accept that token (HTTP $status)."
    have security && security add-generic-password -U -s "$SERVICE" -a "$USER" -w "$token"
  fi
  version="$(json_get "$tmp/release.json" 'r.tag_name.replace(/^v/,"")')"
  name="Mac-Cleaner-$version.zip"
  url="$(json_get "$tmp/release.json" "r.assets.filter(function(x){return x.name=='$name'})[0].url")"
  sums="$(json_get "$tmp/release.json" "r.assets.filter(function(x){return x.name=='SHA256SUMS'})[0].url")"
  bold "Downloading Mac Cleaner $version…"
  curl -fsSL ${token:+-H "Authorization: Bearer $token"} -H "Accept: application/octet-stream" -o "$tmp/$name" "$url"
  curl -fsSL ${token:+-H "Authorization: Bearer $token"} -H "Accept: application/octet-stream" -o "$tmp/SHA256SUMS" "$sums"
  (cd "$tmp" && grep " $name\$" SHA256SUMS | shasum -a 256 -c - >/dev/null) || die "The download is corrupt (checksum mismatch)."
  zip="$tmp/$name"
fi

mkdir -p "$tmp/unpacked" "$APPS"
if have ditto; then ditto -x -k "$zip" "$tmp/unpacked"; else unzip -q "$zip" -d "$tmp/unpacked"; fi
[ -d "$tmp/unpacked/$APP_NAME" ] || die "The download doesn't contain $APP_NAME."

have osascript && osascript -e 'tell application id "com.seth-person.mac-cleaner" to quit' >/dev/null 2>&1 || true
rm -rf "$APP"
# The 0.2.0 browser-based version lived here; the app replaces it.
legacy="$HOME/Applications/$APP_NAME/Contents/MacOS/Mac Cleaner"
[ -f "$legacy" ] && head -c 2 "$legacy" | grep -q '#!' && rm -rf "$HOME/Applications/$APP_NAME"
mv "$tmp/unpacked/$APP_NAME" "$APP"
have xattr && xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

bold "Mac Cleaner is installed in $APPS."
if [ "${MACCLEAN_NO_LAUNCH:-}" != "1" ] && have open; then open "$APP"; fi
