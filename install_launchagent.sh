#!/bin/bash
# Installs a macOS LaunchAgent that runs server.py silently in the
# background, starting at login. Run this once from wherever you cloned
# this project: `./install_launchagent.sh`
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$(command -v python3)"
PLIST_PATH="$HOME/Library/LaunchAgents/com.arxivdigest.server.plist"

if [ -z "$PYTHON_BIN" ]; then
  echo "python3 not found on PATH -- install Python 3.8+ first." >&2
  exit 1
fi

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.arxivdigest.server</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$SCRIPT_DIR/server.py</string>
    <string>--no-browser</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>/tmp/arxivdigest.log</string>
  <key>StandardErrorPath</key><string>/tmp/arxivdigest.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

echo "Installed and started. Open http://localhost:8765 in your browser and bookmark it."
echo "Logs: /tmp/arxivdigest.log"
