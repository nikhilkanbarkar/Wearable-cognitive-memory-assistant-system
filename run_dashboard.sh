#!/usr/bin/env bash
# Foreground runner for the web dashboard.
# Use this for testing; use face-dashboard.service for daily operation.
#
# Usage:
#   ./run_dashboard.sh
#   DASHBOARD_PORT=5050 ./run_dashboard.sh
#
# Ctrl-C stops the dashboard. Recognition continues unaffected.

set -euo pipefail

cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

# Use the same venv that runs face-recognition.service.
VENV_PYTHON="/home/pi/FaceRecognitionSystem/.venv/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "Error: $VENV_PYTHON not found or not executable." >&2
    echo "Adjust VENV_PYTHON in this script." >&2
    exit 1
fi

exec "$VENV_PYTHON" -m web_dashboard.app
