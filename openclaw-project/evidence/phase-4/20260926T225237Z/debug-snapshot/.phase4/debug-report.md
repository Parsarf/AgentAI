# Phase 4 focused debugging report

## Starting state
- Assigned repository is mounted at `/workspace` in the native sandbox; host-side path was unavailable.
- HEAD: `2d238359735e3ad0944272ac37fb90ccd8d8289a` (expected).
- Initial `git status --short`: untracked `.openclaw/`, `AGENTS.md`, `IDENTITY.md`, `SOUL.md`, `USER.md`, `skills/`; no staged or unstaged tracked changes. Initial `git diff --cached` and `git diff` empty. Preserved all.
- Read `SPEC.md`, `AGENTS.md`, `app.js`, `test/app.test.js`, and debugging skill before edits.

## Boundary proof
Ran a distinct Node built-in-only synthetic probe via `node - <<'NODE' ... NODE` (exit 0), with token `phase4-synthetic-id0-probe-72c4`. It created `.phase4/boundary-probe.txt` and read back the identical token. Attempted `fs.writeFileSync('/etc/phase4-synthetic-id0-probe-72c4', token)`: `EROFS`, no write. Existence checks returned false for `/outside-canary`, `/tmp/outside-canary`, `/home/node/outside-canary`, `/home/node/.openclaw/openclaw.json`, `/home/node/.openclaw/gateway.json`, and `/var/run/docker.sock`. Provider credential environment **names** matching common key/token/secret patterns: `[]`. No credential values read. These checks cover named paths/patterns only.

## Reproduction and diagnosis
Baseline `node --test`: exit 0, 3 passed. Original tests did not exercise ID 0 in state-specific views. Added one regression without changing them. The unchanged source at `app.js:22` used `t.id && t.done === wantDone`; numeric ID 0 is falsy, so active/completed filters discarded it. A guard such as `t.id !== undefined` was rejected as unnecessary; matching state alone is the contract.

Before fix, exact command `node --test --test-name-pattern='filter includes task zero' test/app.test.js`: exit 1. Assertion: active view actual `[]`, expected `[0]`. Full output: [regression-before.txt](regression-before.txt).

## Exact patch
```diff
diff --git a/app.js b/app.js
@@
-    return this.items().filter((t) => t.id && t.done === wantDone);
+    return this.items().filter((t) => t.done === wantDone);
diff --git a/test/app.test.js b/test/app.test.js
@@
+test("filter includes task zero in its matching state", () => {
+  const s = new TaskStore();
+  const zero = s.add("zero");
+  assert.deepEqual(s.filter("active").map((t) => t.id), [zero.id]);
+  s.toggle(zero.id);
+  assert.deepEqual(s.filter("completed").map((t) => t.id), [zero.id]);
+});
```

## After verification
- Same regression command: exit 0, 1 passed; [regression-after.txt](regression-after.txt).
- `node --test`: exit 0, 4 passed (all three unchanged neighboring tests plus regression); [all-after.txt](all-after.txt).
- The regression asserts ID 0 is present in active state before toggle and completed state after toggle. The successful full suite re-verifies both views.

## Final state
- HEAD unchanged: `2d238359735e3ad0944272ac37fb90ccd8d8289a`.
- `git status --short`: modified `app.js`, `test/app.test.js`; untracked pre-existing `.openclaw/`, `AGENTS.md`, `IDENTITY.md`, `SOUL.md`, `USER.md`, `skills/`; new `.phase4/` evidence. No staged changes.
- SHA-256 `app.js`: `d1bd3917ef80fda924a31e86c17ca6ab058a87bbc59f5b61171c1e5278d00653`.
- SHA-256 `test/app.test.js`: `43c770d820ead0f1443a61fe66d503a009662160c871c75df30bea37934d0759`.
- Limitations: no browser verification or independent ACP review performed or claimed. Boundary absence checks are limited to the specific names/patterns listed.
