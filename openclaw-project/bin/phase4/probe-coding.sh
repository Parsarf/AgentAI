set -eu
cd /opt/openclaw-production
image=ghcr.io/openclaw/openclaw@sha256:62832668e3e5e139f745f7d3df892c9251eb53318b7d14a76c410dde1f25d730
probe_root=/opt/openclaw-production/openclaw-state/work/phase4/isolation-probe
mkdir -p "$probe_root/repo" "$probe_root/outside"
chown 1000:1000 "$probe_root/repo"
printf 'synthetic-canary\n' > "$probe_root/outside/canary.txt"
docker image inspect "$image" --format 'ENTRYPOINT={{json .Config.Entrypoint}} CMD={{json .Config.Cmd}}'
docker run --rm --name openclaw-phase4-coding-probe --entrypoint /bin/sh --user 1000:1000 --read-only --network none --cap-drop ALL --security-opt no-new-privileges --memory 768m --memory-swap 1g --cpus 1 --pids-limit 128 --tmpfs /tmp:rw,nosuid,nodev,size=64m,mode=1777 -v "$probe_root/repo:/workspace:rw" -w /workspace "$image" -c '
set -eu
node --version
node -e '\''require("fs").writeFileSync("/workspace/inside.txt", "inside-write-ok"); console.log("inside-write=PASS")'\''
test ! -e /var/run/docker.sock
test ! -e /home/node/.openclaw/openclaw.json
test ! -e /home/node/.openclaw/state/openclaw.sqlite
test ! -e /outside/canary.txt
if node -e '\''require("fs").writeFileSync("/home/node/outside.txt", "denied")'\'' 2>/tmp/outside-error.txt; then echo outside-write=FAIL; exit 1; fi
node -e '\''try { require("fs").readFileSync("/outside/canary.txt");process.exit(1) } catch(e) {if(e.code !== "ENOENT" && e.code !== "EACCES") throw e; console.log("outside-read=PASS")} '\''
printf "socket-and-live-state-absent=PASS\noutside-write=PASS\n"
'
test "$(cat "$probe_root/outside/canary.txt")" = synthetic-canary
printf 'host-canary-unchanged=PASS\n'
