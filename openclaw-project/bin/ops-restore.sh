#!/bin/sh
# Isolated restore drill prep. NEVER touches live state; boots nothing.
# usage: ops-restore.sh <archive.tar.gz> [--start]
set -u
BASE=/opt/openclaw-production
G=openclaw-production-openclaw-gateway-1
[ $# -ge 1 ] || { echo "usage: ops-restore.sh <archive.tar.gz> [--start]"; exit 1; }
ARC=$1; shift || true
[ -f "$ARC" ] || { echo "no archive: $ARC"; exit 1; }
TS=$(date -u +%Y%m%dT%H%M%SZ)
DRILL=$BASE/restore-drill/$TS
mkdir -p "$DRILL" || exit 1
chmod 700 "$BASE/restore-drill" 2>/dev/null
docker cp "$ARC" "$G:/tmp/drill.tar.gz" || exit 1
# Verification stages scratch beside the archive; the CLI runs as `node`,
# so a root-owned copy would be refused (path-security rule). Hand it over.
docker exec -u root "$G" chown node:node /tmp/drill.tar.gz || exit 1
docker exec "$G" node dist/index.js backup verify /tmp/drill.tar.gz --json >"$DRILL/verify.json" || { echo VERIFY_FAIL; exit 1; }
docker exec "$G" node dist/index.js backup restore /tmp/drill.tar.gz --target "/tmp/drill-$TS" --json >"$DRILL/restore.json" || { echo RESTORE_FAIL; exit 1; }
mkdir -p "$DRILL/clone" && docker cp "$G:/tmp/drill-$TS/." "$DRILL/clone/" && docker exec -u root "$G" sh -c "rm -rf '/tmp/drill-$TS' /tmp/drill.tar.gz && chown -R root:root '$DRILL' 2>/dev/null" || true
docker exec "$G" sh -c "rm -rf /tmp/drill-$TS /tmp/drill.tar.gz" 2>/dev/null || true
echo "Clone staged OFFLINE at $DRILL/clone (see its manifest.json for layout)."
echo "Phase 10 drill steps before ANY start: sanitize the clone config"
echo "(telegram channel off, automations/cron off, delivery off, distinct"
echo "port/db) via OPENCLAW_STATE_DIR/OPENCLAW_CONFIG_PATH + config set;"
echo "then config validate; then isolated start. Never overwrite live state."
if [ "${1:-}" = "--start" ]; then
  echo "--start: executed per RUNBOOK in an authorized drill only."
  exit 2
fi
exit 0
