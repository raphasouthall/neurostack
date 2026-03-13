#!/usr/bin/env bash
set -euo pipefail
SCRIPT="${1:-test-full-fedora.sh}"
dnf install -y python3 python3-pip git curl gcc python3-devel 2>&1 | tail -5
echo "--- deps installed ---"
bash "/neurostack/$SCRIPT"
