#!/usr/bin/env bash
# Print the URLs at which the dashboard can be reached.
# Also confirm whether it is currently running.

set -euo pipefail

PORT="${DASHBOARD_PORT:-5000}"

echo "Dashboard URL candidates (port ${PORT}):"
echo

found=0
for ip in $(hostname -I 2>/dev/null || true); do
    if [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "  http://${ip}:${PORT}"
        found=1
    fi
done

HOST="$(hostname 2>/dev/null || true)"
if [[ -n "$HOST" ]]; then
    echo "  http://${HOST}.local:${PORT}   (mDNS, if active)"
fi

if [[ "$found" -eq 0 ]]; then
    echo "  (no non-loopback IPv4 address detected)"
fi

echo
echo -n "Dashboard health: "
if curl -s -o /dev/null -w "%{http_code}" --max-time 2 \
        "http://127.0.0.1:${PORT}/health" 2>/dev/null | grep -q 200; then
    echo "OK (running)"
else
    echo "not running (or not on 127.0.0.1:${PORT})"
fi
