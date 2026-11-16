#!/usr/bin/env bash
# Was exactly this code already tested? Prints `tested=true` or `tested=false` (for $GITHUB_OUTPUT).
#
# True only for a push to main that is a merge commit whose files are IDENTICAL to the pull request's last commit (same git tree), when that commit's own CI run for the
# pull request succeeded. Then running every test again would test the same bytes a second time, and the deploy can start at once. In every other case (a direct push, a
# branch that was behind main so the merge changed files, no green run to point at, any error asking) the answer is false and the full checks run. It can only ever skip a
# run that would have been a repeat; it can never skip one that would have tested something new.
set -uo pipefail
no() { echo "tested=false"; exit 0; }
[ "${GITHUB_EVENT_NAME:-}" = "push" ] || no
read -r _self first second rest < <(git rev-list --parents -n 1 HEAD) || no
[ -n "${second:-}" ] && [ -z "${rest:-}" ] || no                                   # a merge of exactly two parents
[ "$(git rev-parse 'HEAD^{tree}' 2>/dev/null)" = "$(git rev-parse "${second}^{tree}" 2>/dev/null)" ] || no
green=$(gh api "repos/${GITHUB_REPOSITORY}/actions/workflows/platform.yml/runs?head_sha=${second}&status=success&per_page=20" \
          --jq '[.workflow_runs[] | select(.event=="pull_request")] | length' 2>/dev/null) || no
[ "${green:-0}" -ge 1 ] || no
echo "tested=true"
