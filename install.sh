#!/bin/bash
# Installs Mac Cleaner as an app in ~/Applications that updates itself.
#
#   ./install.sh               install (or reinstall) from this folder
#   ./install.sh --latest      install the newest GitHub release instead
#   ./install.sh --uninstall   remove the app (your settings and scans in ~/.macclean stay)
#
# After this, updates happen from inside the app: About & updates -> Update.
set -euo pipefail

REPO="seth-person/seths-Mac-cleaner"
ROOT="${MACCLEAN_INSTALL_ROOT:-$HOME/Library/Application Support/Mac Cleaner}"
APPS_DIR="${MACCLEAN_APPS_DIR:-$HOME/Applications}"
APP="$APPS_DIR/Mac Cleaner.app"
PY="${MACCLEAN_PYTHON:-/usr/bin/python3}"
SERVICE="Mac Cleaner GitHub"
PORT=8765

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf '\nError: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

stop_running() {
  if have lsof; then
    for pid in $(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true); do
      if ps -o command= -p "$pid" 2>/dev/null | grep -q "macclean"; then kill "$pid" 2>/dev/null || true; fi
    done
  fi
}

if [ "${1:-}" = "--uninstall" ]; then
  stop_running
  rm -rf "$APP" "$ROOT"
  have security && security delete-generic-password -s "$SERVICE" >/dev/null 2>&1 || true
  bold "Mac Cleaner removed. Your settings, scans and history are still in ~/.macclean."
  exit 0
fi

# --- Python ------------------------------------------------------------------
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
  xcode-select --install >/dev/null 2>&1 || true
  die "Mac Cleaner needs Python 3.9 or newer, which comes with Apple's Command Line Developer Tools.
macOS should now be offering to install them. Once that's done, run this installer again."
fi

# --- GitHub token (the repository is private) ---------------------------------
token=""
read_token() {
  if [ -n "${MACCLEAN_GITHUB_TOKEN:-}" ]; then token="$MACCLEAN_GITHUB_TOKEN"; return; fi
  if have security; then token="$(security find-generic-password -s "$SERVICE" -w 2>/dev/null || true)"; fi
}
api_status() {  # HTTP status for a GitHub API path, with the token if we have one
  if [ -n "$token" ]; then
    curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $token" "https://api.github.com/repos/$REPO$1"
  else
    curl -s -o /dev/null -w '%{http_code}' "https://api.github.com/repos/$REPO$1"
  fi
}
ensure_token() {
  read_token
  [ "${MACCLEAN_SKIP_TOKEN:-}" = "1" ] && return 0
  if [ -n "$token" ] && [ "$(api_status "")" = "200" ]; then return 0; fi
  if [ -z "$token" ] && [ "$(api_status "")" = "200" ]; then return 0; fi  # public repo: no token needed
  echo
  bold "Updates need a GitHub token"
  cat <<'EOF'
The repository is private, so the app needs permission to download new releases.
  1. Open https://github.com/settings/personal-access-tokens/new
  2. Name it "Mac Cleaner", set Repository access to "Only select repositories"
     and pick seths-Mac-cleaner, then under Permissions give Contents: Read-only.
  3. Generate it and paste it below (it's stored in your Keychain, nowhere else).
Press Enter to skip; you can add it later from the app.
EOF
  if [ ! -r /dev/tty ]; then echo "(no terminal to ask on; skipping)"; token=""; return 0; fi
  printf 'Token: '
  IFS= read -rs token </dev/tty || token=""
  echo
  [ -z "$token" ] && { echo "Skipped. Updates won't work until you add a token in the app."; return 0; }
  if [ "$(api_status "")" != "200" ]; then
    echo "GitHub didn't accept that token. You can add one later from the app."
    token=""
    return 0
  fi
  if have security; then
    security add-generic-password -U -s "$SERVICE" -a "$USER" -w "$token"
    echo "Saved to your Keychain."
  fi
}

# --- Get the code ---------------------------------------------------------------
SRC=""
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

ensure_token

if [ "${1:-}" != "--latest" ] && [ -n "$here" ] && [ -f "$here/macclean/__init__.py" ]; then
  SRC="$here"
else
  bold "Downloading the latest release…"
  auth=()
  [ -n "$token" ] && auth=(-H "Authorization: Bearer $token")
  rel="$(curl -fsSL ${auth[@]+"${auth[@]}"} -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/$REPO/releases/latest")" \
    || die "Couldn't fetch the latest release (is the token set up?)."
  asset_url() { "$PY" -c 'import json,sys; r=json.load(sys.stdin); print(next(a["url"] for a in r["assets"] if a["name"]==sys.argv[1]))' "$1" <<<"$rel"; }
  ver="$("$PY" -c 'import json,sys; print(json.load(sys.stdin)["tag_name"].lstrip("vV"))' <<<"$rel")"
  name="mac-cleaner-$ver.tar.gz"
  curl -fsSL ${auth[@]+"${auth[@]}"} -H "Accept: application/octet-stream" -o "$tmp/$name" "$(asset_url "$name")"
  curl -fsSL ${auth[@]+"${auth[@]}"} -H "Accept: application/octet-stream" -o "$tmp/SHA256SUMS" "$(asset_url SHA256SUMS)"
  (cd "$tmp" && grep " $name\$" SHA256SUMS | shasum -a 256 -c - >/dev/null) || die "Download failed its checksum."
  mkdir "$tmp/src" && tar -xzf "$tmp/$name" -C "$tmp/src"
  SRC="$tmp/src"
fi

VERSION="$("$PY" -c 'import sys; sys.path.insert(0, sys.argv[1]); import macclean; print(macclean.__version__)' "$SRC")"
bold "Installing Mac Cleaner $VERSION"

# --- Install the code -----------------------------------------------------------
stop_running
mkdir -p "$ROOT/versions"
dest="$ROOT/versions/$VERSION"
rm -rf "$dest.new"
mkdir -p "$dest.new"
cp -R "$SRC/macclean" "$dest.new/"
find "$dest.new" -name __pycache__ -type d -prune -exec rm -rf {} +
rm -rf "$dest"
mv "$dest.new" "$dest"
ln -sfn "versions/$VERSION" "$ROOT/current"
[ -f "$SRC/install.sh" ] && cp "$SRC/install.sh" "$ROOT/install.sh" && chmod +x "$ROOT/install.sh"

# --- The .app ---------------------------------------------------------------------
# A small launcher: starts the dashboard server in the background and exits,
# so opening the app again just brings the dashboard back up in your browser.
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat >"$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Mac Cleaner</string>
  <key>CFBundleDisplayName</key><string>Mac Cleaner</string>
  <key>CFBundleIdentifier</key><string>com.seth-person.mac-cleaner</string>
  <key>CFBundleExecutable</key><string>Mac Cleaner</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
EOF
cat >"$APP/Contents/MacOS/Mac Cleaner" <<EOF
#!/bin/bash
ROOT="$ROOT"
LOG="\$HOME/Library/Logs/Mac Cleaner.log"
mkdir -p "\$(dirname "\$LOG")"
export PYTHONPATH="\$ROOT/current"
cd "\$ROOT" || exit 1
nohup "$PY" -m macclean serve --port $PORT >>"\$LOG" 2>&1 &
exit 0
EOF
chmod +x "$APP/Contents/MacOS/Mac Cleaner"
have xattr && xattr -dr com.apple.quarantine "$APP" "$ROOT" 2>/dev/null || true

echo
bold "Done. Mac Cleaner $VERSION is in $APPS_DIR."
echo "Open it like any app (Spotlight: \"Mac Cleaner\"). New versions show an Update button inside the app."
if [ "${MACCLEAN_NO_LAUNCH:-}" != "1" ] && have open; then open "$APP"; fi
