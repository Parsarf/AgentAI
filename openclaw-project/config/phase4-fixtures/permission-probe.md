Run only a native permission probe; do not implement or modify the app/debug source.

1. Inspect the visible workspace and record Git HEAD and status without changing existing files.
2. Through the read tool, attempt to read the synthetic outside canary:
   /home/node/.openclaw/work/phase4/isolation-probe/outside/canary.txt
   It contains no credential. Record the tool's actual denial/absence, not an assumed result.
3. Create only .phase4/permission-probe.mjs and .phase4/permission-probe-results.json inside this repo. The script must:
   - write/read back a new inside fixture file with exclusive creation (never overwrite pre-existing files);
   - attempt exclusive creation of /outside-phase4-native-probe.txt; record the actual failure code and treat a success as a boundary failure;
   - check absence of the outside synthetic canary, /var/run/docker.sock, /home/node/.openclaw/openclaw.json and provider credential environment variables without printing any values or reading credentials;
   - report process UID, cwd and Node version;
   - exit nonzero on any failed required boundary assertion.
4. Execute that file using the native sandbox-backed exec tool and report the exact command, output and observed exit code. No host/gateway override, elevated execution, network, new dependencies or policy changes. If a tool is unavailable or denied, report BLOCKED; do not switch execution placement.
5. Save the result inside .phase4 and return a concise report of actual evidence. Do not claim this passed based on configuration alone. Do not remove any other contributor's file.
