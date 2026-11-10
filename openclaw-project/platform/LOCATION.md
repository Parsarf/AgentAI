# Customer device location

`lumina_request_location` is an authenticated native tool tied to a funded live
request and its runtime ownership proof. It asks through the signed-in Lumina
website, never through the server browser. The page must be open and visible;
Chrome controls the actual permission prompt and may reuse an existing decision.
Extension sidebar/Telegram clients without the website open time out honestly.

The tool waits up to 120 seconds and returns `granted` with latitude, longitude
and accuracy in metres, or `denied`, `unavailable`, `timeout`, `cancelled`.
One consent attempt per task prevents repeated nagging. A new customer message
creates a new task, allowing another attempt after permission settings change.
A 15-second claimed browser lease is renewed every five seconds; competing tabs
cannot submit an answer. An ignored prompt expires as timeout, never denial.
Stop/revoked funding/task termination invalidate results. The worker parks on
`location_permission`, preserving normal execution time and cancellation.

Coordinates are not in public events, logs, localStorage or sessionStorage.
The transient database position is cleared when consumed and after expiration
by the normal worker housekeeping (including when execution is switched off).
After a process outage it is cleared when housekeeping resumes; this is not
cryptographic deletion of database pages/backups. The agent receives coordinates
as tool output, so its native conversation history can contain them. Coordinates
are device-reported data with reported accuracy, not verified GPS/address proof.

## Release order

1. Back up the database using the normal release process. Run Django `migrate`
   (0017 adopts checksummed SQL migration 0035) before starting updated services.
2. Release backend, tool relay and request worker together. Restart the relay
   and worker. Serve the updated frontend bundle through the normal UI release.
3. Refresh existing cells through the normal supervisor configuration/wake path:
   it updates workspace guidance and installs the updated tool-origin plugin.
   Already running cells need that refresh/restart before the new tool can work.
4. Verify in real Chrome on the deployed HTTPS origin: Allow, Block, existing
   blocked permission, ignored prompt, Stop and two tabs. A real customer/model
   run is a release acceptance step; local synthetic checks do not prove rollout.

Rollback: restore prior app/relay/worker/UI and cell plugin/guidance together;
leave the additive table/migration in place. Do not edit migration checksums.
No new external service or API key is required. Permissions-Policy must permit
geolocation for the customer page's own origin; generated executable app frames
remain denied location access.

## Checks

- `python -m unittest tests.test_location tests.test_browser_tool tests.test_tool_origin tests.test_native_run tests.test_request_worker tests.test_cell_config`
- `python manage.py test accounts.test_location`
- In `lumina`: `npm test`, `npm run build`.
- Start `python tests/preview_chat.py`, then `node tests/location-browser.mjs`.
  This runs the production bundle in local Chrome with synthetic granted
  coordinates, denied permissions and an ignored request plus explicit refusal,
  at 390px and 1440px. It does not collect the operator's location.

## Local verification — 7 November 2026

Frontend suite: 469 tests passed; after adding the explicit Share-button retry,
all 9 location UI tests and the production build passed. Backend regression
suite: 133 tests passed, plus the expanded 11 location tests. Django HTTP test
passed with CSRF enforced. Fresh database migration and migration-drift check
passed. Chrome passed all six viewport/outcome cases above. The runtime hook
also passed Node syntax checking. Existing bundle-size warnings remain.

No production deployment, real customer location collection, or paid agent run
was performed. The deployed HTTPS permission prompt and a real native tool call
still require release acceptance.
