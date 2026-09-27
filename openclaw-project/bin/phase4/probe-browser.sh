set -eu
umask 077
cd /opt/openclaw-production
probe_env=$(mktemp /tmp/openclaw-phase4-browser-probe.XXXXXX)
trap 'docker inspect openclaw-phase4-browser-probe --format "browser-probe-state={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}}"; docker logs --tail 12 openclaw-phase4-browser-probe 2>&1; docker rm -f openclaw-phase4-browser-probe >/dev/null 2>&1 || true; rm -f "$probe_env"' EXIT
python3 - "$probe_env" <<'PY'
import secrets,sys
open(sys.argv[1],'w').write('OPENCLAW_BROWSER_CDP_AUTH_TOKEN='+secrets.token_hex(24)+'\nOPENCLAW_BROWSER_CDP_PORT=9222\nOPENCLAW_BROWSER_HEADLESS=1\nOPENCLAW_BROWSER_ENABLE_NOVNC=0\nOPENCLAW_BROWSER_NO_SANDBOX=1\n')
PY
docker run -d --name openclaw-phase4-browser-probe --user 1000:1000 --read-only --network bridge --cap-drop ALL --security-opt no-new-privileges --memory 768m --memory-swap 1g --cpus 1 --pids-limit 128 --tmpfs /tmp:rw,nosuid,nodev,size=256m,mode=1777 --tmpfs /run:rw,nosuid,nodev,size=16m,mode=1777 --env-file "$probe_env" -p 127.0.0.1::9222 openclaw-sandbox-browser:phase4-2026.9.6 >/dev/null
port=$(docker port openclaw-phase4-browser-probe 9222/tcp)
python3 - "$probe_env" "$port" <<'PY'
import json,sys,time,urllib.request,urllib.error
assert sys.argv[2].startswith('127.0.0.1:'), 'control exposed publicly'
token=open(sys.argv[1]).readline().strip().split('=',1)[1]
url='http://'+sys.argv[2]+'/json/version'
for i in range(40):
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':'Bearer '+token}),timeout=2) as r:
   data=json.load(r); assert 'Browser' in data; break
 except (urllib.error.URLError,TimeoutError,OSError):
  time.sleep(.5)
else: raise RuntimeError('browser relay did not start')
for label,headers in [('no_auth',{}),('wrong_auth',{'Authorization':'Bearer invalid-synthetic-token'})]:
 try:
  urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=3)
  raise RuntimeError(label+' incorrectly admitted')
 except urllib.error.HTTPError as e:
  assert e.code==401, (label,e.code);print(label+'=DENIED_401')
print('authenticated_control=PASS')
print('loopback_only=PASS')
print('browser_version='+data['Browser'])
PY
docker exec openclaw-phase4-browser-probe sh -c 'test ! -e /var/run/docker.sock; test ! -e /home/node/.openclaw/state/openclaw.sqlite; test ! -e /home/node/.openclaw/openclaw.json; printf "socket-and-live-state-absent=PASS\n"'
