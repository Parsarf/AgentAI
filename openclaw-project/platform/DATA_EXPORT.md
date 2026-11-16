# Your data export: what is in the archive

Roadmap #19. `POST /v1/exports` asks for one; the account-jobs timer makes it; `POST /v1/exports/<id>/ticket` gives a single-use link that expires in 15 minutes. The
archive is kept for 7 days (the `exports` row of the retention table). Code: `agentai_platform/data_lifecycle.py` (`EXPORT`, `run_export`). Schema version: **1**.

A ZIP file. `manifest.json` lists every file in it: what it is, how many items it holds, its size and its SHA-256. Every JSON file is a list of records exactly as Lumina
holds them, one object per record, with the column names as keys. Times ending in `_epoch` are seconds since 1970 (UTC); times ending in `_at` are ISO 8601.

| File | What it holds |
|---|---|
| `conversations/conversations.json`, `messages.json`, `projects.json` | Chats, every message in them, and projects |
| `tasks/tasks.json` | Every task you asked for and how it ended |
| `tasks/plans.json`, `documents.json`, `plan_revisions.json`, `plan_phase_runs.json`, `plan_proposals.json` | Plans, tables, forms, documents and cards shown in chats, with their versions |
| `tasks/long_jobs.json`, `long_job_checkpoints.json`, `browser_runs.json` | Long jobs and browser tasks |
| `files/files.json` and `files/made/<id>/v<n>/<name>` | Files your assistant made, every version, as the original bytes |
| `files/uploads.json` and `files/uploaded/<id>/<name>` | Files you uploaded |
| `memory/project_memory.json`, `long_term_memory.json`, `saved_choices.json`, `skills.json`, `skill_versions.json` | What your assistant remembers |
| `automation/schedules.json`, `schedule_runs.json`, `watchers.json` | Schedules and watchers |
| `connections/connections.json`, `grants.json`, `remote_tools.json`, `remote_tool_choices.json`, `automatic_approvals.json`, `removed.json`, `saved_logins.json` | What is connected and what it may reach. **Never tokens, passwords, keys or sealed secrets**: saved logins are names only |
| `actions/actions.json`, `workflows.json`, `questions.json` | Changes prepared or made in connected services, and what was asked of you |
| `settings/spending_limits.json`, `plan_settings.json` | Your limits and settings |
| `usage/receipts.json`, `usage.json` | What each task cost |

`manifest.json` also has `not_included`: what is left out and why (sealed tokens, one-time links and codes, the 30-day step-by-step timeline, internal bookkeeping).

An organization's owner may export the whole organization (`organization=1`): the same layout once per member under `members/<account id>/`. A member exports only
their own data.

A new version of this layout gets a new `schema_version`; fields are added, not renamed.
