# Phase 4 resumed native execution

Gate 4 remains **BLOCKED**, with native build and debugging proof complete. Browser and ACP review remain unrun.

## Verified

- Normal SSH approval is available again. Saved ChatGPT Plus quota was checked through protected native account-usage RPC; no account identifiers or credentials exported.
- Fixed an installed same-version packaging defect: Codex setup could not resolve the host `openclaw` SDK peer package. Derived image adds only `/app/node_modules/openclaw -> /app`; isolated module import passed, Gateway health HTTP200 after restart.
- Native model validation checked both worker refs without errors. Applied six scoped fields, exactly compared all authored values and validated config. CLI printed successful application but did not exit due plugin cleanup; bounded command returned124. This is not a clean native CLI exit.
- Native Codex permission run49cac1c7-f8b1-455e-bac2-60cf427ef006, session645ba6b3-dd48-4dc7-a9fc-3407920ede14, turn01a0dff0-5a8d-7393-a4ca-06e057e97b19 used profile auth, gpt-6-sol, harnesscodex, CodeMode off and sandbox_exec. Tool calls included two mapping/availability failures; outside read was denied. No backend fallback.
- Operator inspected actual container mounts: only assigned board plus protected skills; user1000, networknone, rootread-only. Outside root write EROFS; outside canary, Gateway state and Docker socket absent; provider credential environment names absent. Original probe's write/read fixture was scratch `/tmp`; builder subsequently completed an explicit project fixture; exported results inspected, all checks passed.
- Configuration valid, warnings[]. Secret audit has no plaintext/unresolved references; exit1 is one informational OAuth LEGACY_RESIDUE, outside static SecretRef migration.

## Native build complete; browser and ACP pending

Main coordinator run85475c50-6cf7-471f-bec5-5d885402d747, session723d1f47-e2c2-4f39-a586-9247b8e15edf, native turn01a0dff3-6af0-7522-aee5-41e70d87038e successfully used sessions_spawn and sessions_yield. Completed child session17b39191-436f-4770-8b55-70b5d354778b, key `agent:codex-builder:subagent:728806eb-8b00-4faa-af1a-561b5274daf1`, starts from board HEAD6ba1d0d7ae3ff7aec95f02e13730dda4b5068f1d. Child completed natively: seven behavioral tests passed, explicit repo probe passed, and private HTTP smoke check passed then stopped. Source export is in `board-snapshot/`; all8 application file hashes match native tested manifest (`board-source-integrity.json`). This passes the native build subcheck, not full app acceptance. Main default remains Anthropic; per-run Sol override only.

## Cost and remaining gates

Latest shared account observation: five-hour98% used, week15%, zero credit balance. Native token totals are in manifest; invoice cost unknown. Shared quota changes are not attributable solely to these runs. No purchased credits, API fallback or Anthropic cap changes. Browser verification and independent ACP review have not run; native debugging proof passed: same regression exit1 before/exit0 after; all4 tests pass, minimal source fix and original3 neighbors preserved. Artifacts in `debug-snapshot/`. Earlier gates remain pending under the owner's recorded Phase4 exception.

## Recovery

Private archive `phase4-native-workers-20260926T224652Z/openclaw.tar.gz` verified; hash in manifest. Opaque Codex SQLite archive files were not live-snapshotted/integrity-checked; archive verification is not database consistency proof. Recovery has not been tested. Restore only authored fields/Compose and preserve newer authentication and unrelated edits.

Security audit: zero critical, two warnings (explicit coding profile overrides; model-tier heuristic flags selected Codex model), no secret diagnostics. Doctor exited1 due active builder database lease during historical migration; later checks refused. Offline retry pending; no forced migration applied.

Debug run4086f835-92aa-4dff-a057-625242ae7f62, session4200bd53-ee85-468a-9422-66a9770d54ca, native turn01a0dff8-a0d1-7f70-ae04-7e0d714ec1e9: gpt-6-sol, profile auth, harnesscodex, CodeMode off, sandbox_exec/apply_patch/write successful. Two failed path-tool attempts preceded sandbox-backed success. No fallback. Before/after source hashes match exported evidence.

## Final checkpoint and resume

ChatGPT quota98% used, zero credits, reset2026-09-27 03:37:23UTC. New inference stopped before exceeding the included allowance. Proxy admission remains unavailable until00:00UTC under the existing caps. Neither billing route was expanded.

Doctor's offline retry precheck found the main Phase4 coordinator collecting the completed child. The check aborted before Gateway shutdown or state migration; health still HTTP200. No doctor --fix, offline archive or restore was performed in that attempt. Earlier native backup remains the recovery artifact with its documented SQLite consistency limitations.

Changed-artifact pattern scan:36 files, no private-key/API-token matches; git diff --check exit0. Pattern coverage is limited. No raw auth/profile state was exported. Preserve all unrelated edits and captured repo baselines.

Resume with a protected quota read and coordinator status check. Once allowance is available, finish restricted native browser verification on the recorded source snapshot, configure/probe the independent ACP reviewer using the existing authorized billing route, disposition findings and rerun affected checks. Retry Doctor only when the Gateway's native runs are quiescent, using scoped stopped-state maintenance and health recovery. Phase5/7A have not started. Earlier gates remain pending; no cron was recreated.
