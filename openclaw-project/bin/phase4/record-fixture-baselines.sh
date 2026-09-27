set -eu
cd /opt/openclaw-production
docker compose exec -T openclaw-gateway sh -c '
set -eu
for repo in board debug-repo; do
  repo_dir=/home/node/.openclaw/work/phase4/$repo
  if test ! -e "$repo_dir/.git"; then
    git -C "$repo_dir" init -q -b phase4-fixture
    if test "$repo" = board; then git -C "$repo_dir" add SPEC.md; else git -C "$repo_dir" add SPEC.md app.js test; fi
    git -C "$repo_dir" -c user.name="OpenClaw fixture preparation" -c user.email="fixture@localhost" commit -q -m "Record Phase 4 fixture baseline"
  fi
  printf "%s starting-revision=" "$repo"
  git -C "$repo_dir" rev-parse HEAD
  git -C "$repo_dir" status --short
 done
'
docker run --rm --name openclaw-phase4-baseline-probe --entrypoint /bin/sh --user 1000:1000 --read-only --network none --cap-drop ALL --security-opt no-new-privileges --memory 768m --memory-swap 1g --cpus 1 --pids-limit 128 --tmpfs /tmp:rw,nosuid,nodev,size=64m,mode=1777 -v /opt/openclaw-production/openclaw-state/work/phase4/debug-repo:/workspace:ro -w /workspace ghcr.io/openclaw/openclaw@sha256:62832668e3e5e139f745f7d3df892c9251eb53318b7d14a76c410dde1f25d730 -c 'node --test'
