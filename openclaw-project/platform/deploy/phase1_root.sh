#!/bin/bash
# Root steps for deploy/phase1_live.py: the proof asks by creating /tmp/p1-act-<name>.request; this does the step and creates /tmp/p1-act-<name>.done.
# Run as root beside the proof:  systemd-run --unit=p1root --property=RuntimeMaxSec=7000 /opt/agentai-platform/current/deploy/phase1_root.sh
DB=/var/lib/agentai-platform/platform.sqlite3
CUSTODY=/var/lib/agentai-supervisor/custody.sqlite3
CELLS=unix:///run/agentai-cells/docker.sock
NODEBIN=/opt/agentai-native/2026.9.6-node24.16.0/node-v24.16.0-linux-x64/bin
NODE=$NODEBIN/node
ENTRY=/opt/agentai-native/2026.9.6-node24.16.0/cli/node_modules/openclaw/openclaw.mjs
tenant() { sqlite3 -readonly $DB "select tenant_ref from lifecycle_cells where account_id like 'p1b%' limit 1"; }
limit_tenant() { t=$(cat /tmp/p1-limit-tenant 2>/dev/null); case "$t" in aa-[0-9a-f]*) echo "$t" ;; esac; }   # the proof names the tenant whose key is limited for the test (its own, never another customer's: the proof only ever writes its own test account's)
psql_l() { docker exec openclaw-production-postgres-1 psql -U litellm -d litellm -At -c "$1"; }
cleanup_b() {   # only ever a disposable p1b* account's cell: never any other tenant
  t=$(cat /tmp/p1-cleanup-tenant 2>/dev/null)
  case "$t" in aa-[0-9a-f]*) ;; *) return 1 ;; esac
  account=$(sqlite3 -readonly $DB "select account_id from lifecycle_cells where tenant_ref='$t'")
  case "$account" in p1b*) ;; *) return 1 ;; esac
  # The runtime's own registry must forget the cell (`fleet rm`), or the next creation finds its port taken and is rejected; then the leftovers.
  ( cd /var/lib/agentai-fleet && HOME=/var/lib/agentai-fleet DOCKER_HOST=$CELLS PATH=/usr/bin:/bin:$NODEBIN $NODE $ENTRY fleet rm --force $t >/dev/null 2>&1 )
  DOCKER_HOST=$CELLS docker rm -f openclaw-cell-$t >/dev/null 2>&1
  DOCKER_HOST=$CELLS docker network rm openclaw-cell-$t-net >/dev/null 2>&1      # a stale network keeps its subnet and makes the next cell's creation fail
  rm -rf /var/lib/agentai-fleet/.openclaw/fleet/auth-profile-secrets/$t
  mnt=/var/lib/agentai-fleet/.openclaw/fleet/cells/$t
  mountpoint -q $mnt && umount $mnt
  losetup -j /var/lib/agentai-cells/volumes/$t.img | cut -d: -f1 | xargs -r losetup -d
  rm -f /var/lib/agentai-cells/volumes/$t.img; rmdir $mnt 2>/dev/null
  rm -rf /var/lib/agentai-cells/backups/$account
  # The lifecycle worker REQUIRES the supervisor: stopping the supervisor stops it too, and starting the supervisor again does not bring it back. So: stop both, edit, start both.
  systemctl stop agentai-lifecycle-worker agentai-supervisor-native
  sqlite3 $CUSTODY "delete from journal where account='$account'; delete from bindings where account='$account'"
  systemctl start agentai-supervisor-native agentai-lifecycle-worker
  psql_l "delete from \"LiteLLM_VerificationToken\" where key_alias='$t'" >/dev/null
}
rm -f /tmp/p1-act-*
while true; do
  for name in kill-worker kill-cell limit-on limit-off cleanup-b; do
    if [ -f /tmp/p1-act-$name.request ] && [ ! -f /tmp/p1-act-$name.done ]; then
      case $name in
        kill-worker) systemctl restart agentai-request-worker ;;
        kill-cell)   DOCKER_HOST=$CELLS docker restart openclaw-cell-$(tenant) >/dev/null ;;
        limit-on)    psql_l "update \"LiteLLM_VerificationToken\" set rpm_limit=2 where key_alias='$(limit_tenant)'" >/dev/null ;;
        limit-off)   psql_l "update \"LiteLLM_VerificationToken\" set rpm_limit=120 where key_alias='$(limit_tenant)'" >/dev/null ;;
        cleanup-b)   cleanup_b ;;
      esac
      touch /tmp/p1-act-$name.done; echo "$(date +%T) did $name"
    fi
  done
  sleep 0.5
done
