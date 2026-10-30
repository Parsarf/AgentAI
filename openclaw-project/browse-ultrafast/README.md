# browse-ultrafast

Vendored copy of browser-use's **jev-ultrafast** (MIT, see LICENSE), pinned to commit
`1231850a0bf1a0c0341fe408ef1668dbbfdfac46` of https://github.com/browser-use/jev-ultrafast, plus the hash-pinned
dependency list (`requirements.txt`, exported from its `uv.lock`). It is the experimental browser engine that the
owner can switch on for their own account (safety switch `standard_browser`, see `plans/product/FEATURE_SWITCHES.md`
and `platform/agentai_platform/browse/ultrafast.py`).

Do not edit the vendored files; to update, re-vendor a newer commit, re-export the requirements and review the diff.
Install on the server with `python3 openclaw-project/bin/update-ultrafast.py` (plan) and `--apply`.
