#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_DIR="${XDG_DESKTOP_DIR:-}"

if [[ -z "$DESKTOP_DIR" ]]; then
  if [[ -d "$HOME/Desktop" ]]; then
    DESKTOP_DIR="$HOME/Desktop"
  elif [[ -d "$HOME/桌面" ]]; then
    DESKTOP_DIR="$HOME/桌面"
  else
    DESKTOP_DIR="$HOME/Desktop"
  fi
fi

mkdir -p "$DESKTOP_DIR"
shortcut="$DESKTOP_DIR/EDU-Mate.desktop"

cat > "$shortcut" <<EOF
[Desktop Entry]
Type=Application
Name=EDU-Mate
Comment=启动 EDU-Mate 课堂助手
Exec=$ROOT_DIR/scripts/launch_desktop_app.sh
Path=$ROOT_DIR
Icon=applications-education
Terminal=true
StartupNotify=true
Categories=Education;Utility;
EOF

chmod +x "$shortcut"

if command -v gio >/dev/null 2>&1; then
  gio set "$shortcut" metadata::trusted true >/dev/null 2>&1 || true
fi

echo "Installed desktop shortcut: $shortcut"
