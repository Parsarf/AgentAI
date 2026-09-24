# Phase 2 — Sandbox, tool policy, approvals

Continue from accepted Gate 1. Read the OpenClaw phase index, architecture and
build log; verify the installed-version docs for sandboxing, tool profiles,
exec approvals, approval delivery and scheduled runs before editing config.
Keep the single owner agent usable while reducing its authority.

## Work

1. Configure supported sandbox isolation and per-agent tool policy. Give only
   the tools needed for the current phase. Separate read-only, workspace write,
   host execution, messaging, configuration and credential access. Use actual
   OpenClaw controls; do not build a duplicate approval engine.
2. Implement the approved autonomy policy as enforceable tool/exec policy.
High-impact actions (money, messages to other people, external deletion,
production deployment or main-branch push, security-policy changes, plugin
installs, new credential access) need the owner's authorization under the
approved architecture. Unattended runs get a stricter policy. If a risk class
cannot be expressed natively, demonstrate a safe denial and report the gap
before adding any extension.
3. Run safe negative probes: a sandboxed process tries to read a host-only
   sentinel outside its workspace; a disallowed tool call is denied; an exec
   command subject to approval cannot run before approval; denial and expiry
   leave no side effect. Check the **actual** interactive approval surfaces
   offered by the installed channel/UI. Do not assume Telegram supports a
   particular approval kind because the original brief says so.
4. Run doctor, sandbox-specific diagnostics and security audit. Record policy
   files, sanitized probe results, exceptions and cost in `BUILD_LOG.md`.

## Gate 2

The sandbox cannot read the host sentinel, high-risk actions pause or deny as
specified, and a refused request leaves no effect. The owner has tested the
documented approval surface. Stop if required isolation or approval is absent.
