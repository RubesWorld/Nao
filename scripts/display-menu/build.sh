#!/bin/bash
# Compile main.swift into a real .app bundle in ~/Applications.
#
# A bundle (not a bare binary) is required: LSUIElement lives in Info.plist,
# and without it the app takes a Dock icon and a menu bar of its own.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Applications/Display Mode.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Display Mode</string>
    <key>CFBundleDisplayName</key>
    <string>Display Mode</string>
    <key>CFBundleIdentifier</key>
    <string>com.nao.display-menu</string>
    <key>CFBundleExecutable</key>
    <string>DisplayMode</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
PLIST

swiftc -O -o "$APP/Contents/MacOS/DisplayMode" "$SRC/main.swift"

# Ad-hoc signature. Unsigned bundles get killed on some macOS versions and
# lose any TCC grants across rebuilds.
codesign --force --sign - "$APP"

echo "Built $APP"
