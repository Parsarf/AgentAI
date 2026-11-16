#!/usr/bin/env bash
# The checks, in parts. CI runs each part as its own job, in parallel; `all` runs every part on this machine, in parallel, and is THE command to run before opening a pull
# request: it is the same script CI runs, so "green here" and "green there" mean the same thing. (.github/workflows/platform.yml lists the same parts; a test keeps the two equal.)
#
#   ci/run.sh parts                 the blocking parts, one per line
#   ci/run.sh accounts 2 3          one part: the account API tests, share 2 of 3
#   ci/run.sh all                   every blocking part at once; a summary, and the end of the log of any part that failed
#
# Parts: accounts i n | platform i n | acceptance | extras | lumina | browse (report-only) | report (report-only platform modules)
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACCOUNT_SHARES=3
PLATFORM_SHARES=2
PY="${PYTHON:-}"; [ -z "$PY" ] && { [ -x "$ROOT/platform/.venv/bin/python" ] && PY="$ROOT/platform/.venv/bin/python" || PY=python; }

parts() {
  for i in $(seq 1 $ACCOUNT_SHARES); do echo "accounts $i $ACCOUNT_SHARES"; done
  for i in $(seq 1 $PLATFORM_SHARES); do echo "platform $i $PLATFORM_SHARES"; done
  echo acceptance; echo extras; echo lumina
}

# Modules of one share. Every module is in exactly one share (they are dealt out by size, largest first, to the share that has least so far), so nothing can be left out.
share() {  # kind index count
  "$PY" - "$1" "$2" "$3" "$ROOT/platform" <<'PYEOF'
import os, sys
kind, index, count, root = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
if kind == 'accounts':
    names = sorted(f[:-3] for f in os.listdir(os.path.join(root, 'accounts')) if f.startswith('test') and f.endswith('.py'))
    sized = [(os.path.getsize(os.path.join(root, 'accounts', n + '.py')), 'accounts.' + n) for n in names]
else:
    names = [l.strip() for l in open(os.path.join(root, 'tests', 'ci_blocking.txt')) if l.strip()]
    sized = [(os.path.getsize(os.path.join(root, 'tests', n + '.py')), 'tests.' + n) for n in names]
bins = [[0, []] for _ in range(count)]
for size, name in sorted(sized, key=lambda x: (-x[0], x[1])):
    least = min(bins, key=lambda b: b[0]); least[0] += size; least[1].append(name)
print(' '.join(sorted(bins[index - 1][1])))
PYEOF
}

run_part() {
  case "$1" in
    accounts)
      cd "$ROOT/platform" || return 1
      export AGENTAI_SESSION_SECRET="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(64))')" AGENTAI_STATE_DIR="$(mktemp -d)" AGENTAI_PUBLIC_ORIGIN="${AGENTAI_PUBLIC_ORIGIN:-https://localhost}"
      # shellcheck disable=SC2046
      "$PY" manage.py test $(share accounts "$2" "$3") --verbosity 1 ;;
    platform)
      cd "$ROOT/platform" || return 1
      # shellcheck disable=SC2046
      "$PY" -m unittest $(share platform "$2" "$3") 2>&1 | tail -n 60; return "${PIPESTATUS[0]}" ;;
    acceptance)
      cd "$ROOT/platform" || return 1
      "$PY" deploy/acceptance.py run --baseline tests/acceptance_baseline.json --out "${RUNNER_TEMP:-$(mktemp -d)}/acceptance.json" ;;
    extras)
      cd "$ROOT/platform" || return 1
      export AGENTAI_SESSION_SECRET="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(64))')" AGENTAI_STATE_DIR="$(mktemp -d)" AGENTAI_PUBLIC_ORIGIN="${AGENTAI_PUBLIC_ORIGIN:-https://localhost}"
      "$PY" manage.py makemigrations --check --dry-run || return 1                      # migration drift
      node deploy/vercel/check.mjs || return 1                                           # website routing
      node --test tests/tool_origin_plugin.test.mjs || return 1
      (cd ../browser-opt && "$PY" -m unittest test_jev_adapter test_route) || return 1  # optional tracks, offline
      (cd ../research-opt && "$PY" -m unittest test_adapter) || return 1
      node --test ../research-opt/plugin/test.mjs || return 1
      (cd ../dashboard && "$PY" -m unittest test_dashboard) ;;                           # the owner dashboard: nothing switchable by one click
    lumina)
      cd "$ROOT/lumina" || return 1
      [ -n "${CI:-}" ] && { npm ci || return 1; }
      npx tsc --noEmit && npx vitest run && npm run build ;;
    browse)
      cd "$ROOT/browse" || return 1
      [ -n "${CI:-}" ] && { npm ci || return 1; }
      node --test --test-timeout=120000 test/ ;;
    report)
      cd "$ROOT/platform" || return 1
      fail=0; out="${GITHUB_STEP_SUMMARY:-/dev/stdout}"; tmp="${RUNNER_TEMP:-$(mktemp -d)}"
      echo "### Report-only platform modules" >> "$out"
      for f in tests/test_*.py; do
        m=$(basename "$f" .py); grep -qx "$m" tests/ci_blocking.txt && continue
        if timeout 300 "$PY" -m unittest "tests.$m" >"$tmp/$m.log" 2>&1; then echo "PASS $m" >> "$out"
        else echo "FAIL $m (see log tail)" >> "$out"; tail -n 15 "$tmp/$m.log" | sed 's/^/    /' >> "$out"; fail=1; fi
      done
      return $fail ;;
    *) echo "unknown part: $1" >&2; return 2 ;;
  esac
}

case "${1:-}" in
  parts) parts ;;
  share) share "$2" "$3" "$4" ;;
  all)
    logs="$(mktemp -d)"; pids=(); names=(); started=$(date +%s)
    while IFS= read -r part; do
      # shellcheck disable=SC2086
      ( run_part $part ) >"$logs/${part// /-}.log" 2>&1 &
      pids+=($!); names+=("$part")
    done < <(parts)
    failed=0
    for i in "${!pids[@]}"; do
      if wait "${pids[$i]}"; then echo "PASS  ${names[$i]}"; else echo "FAIL  ${names[$i]}"; failed=1; echo "----- the end of its log -----"; tail -n 40 "$logs/${names[$i]// /-}.log"; echo "-----"; fi
    done
    echo "$( [ $failed = 0 ] && echo 'ALL PARTS PASSED' || echo 'SOME PARTS FAILED' ) in $(( $(date +%s) - started )) s. Logs: $logs"
    exit $failed ;;
  "") echo "usage: ci/run.sh parts | all | <part>" >&2; exit 2 ;;
  *) run_part "$@" ;;
esac
