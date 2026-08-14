#!/usr/bin/env bash
# de_verify_skill — structural verifier for skills/catalog.yaml
# Usage: verify.sh [skill_id]   (omit to verify the whole catalog)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
exec python3 "$SCRIPT_DIR/verify_skill.py" "$REPO_ROOT" "${1:-}"
