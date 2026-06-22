#!/usr/bin/env bash

# Desktop launcher for EDU-Mate.
# It keeps the terminal open on startup failure so the user can read the cause.

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 1

export APP_OPEN_BROWSER="${APP_OPEN_BROWSER:-1}"
export APP_BROWSER_DELAY_SECONDS="${APP_BROWSER_DELAY_SECONDS:-2}"

echo "Starting EDU-Mate..."
echo "Project: $ROOT_DIR"
echo

"$ROOT_DIR/scripts/dev.sh" app
status=$?

if [[ "$status" -ne 0 ]]; then
  echo
  echo "EDU-Mate failed to start. Exit code: $status"
  echo "Check the messages above, then press Enter to close this window."
  read -r _
fi

exit "$status"
