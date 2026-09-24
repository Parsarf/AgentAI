#!/usr/bin/env bash
set -euo pipefail
exec "${PYTHON_BIN:-python3}" "$(dirname "$0")/backup_bundle.py" backup "$@"
