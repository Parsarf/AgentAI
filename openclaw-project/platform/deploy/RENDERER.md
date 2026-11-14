# The render service (files in any format)

Lets the assistant hand a customer a real PDF, Word, Excel or PowerPoint file, and powers "Download as" in the app.
Without it everything else still works: files are delivered in the format the assistant wrote them in, and the Download-as buttons for PDF, Word and Excel are hidden.

## What runs where

| Piece | Runs as | Does |
|---|---|---|
| `agentai-render.service` (`agentai_platform/render/service_main.py`) | root, on the host | Takes one job at a time over `/run/agentai-render/render.sock` and starts a container for it |
| `lumina-renderer:1` (`deploy/renderer/Dockerfile`) | uid 10001, in the cell engine | Converts the file (`render/engine.py`): LibreOffice, pandoc, Chromium, poppler, openpyxl, Pillow |
| the app, tool relay and request worker | `agentai-platform` | Ask for conversions through the socket (`render/client.py`); they start no container and parse no document |

Each job's container has no network (`--network none`), a read-only root, no capabilities, 1.5 GB of memory, one CPU, 256 processes and 150 seconds.
The job folder (`/var/lib/agentai-render/jobs/<id>`) is removed when the job ends; nothing about the content is logged.

## Install (once)

1. Build the image into the **cell engine** (it has its own image store), from the platform folder of the release:
   `DOCKER_HOST=<cell engine socket> docker build -f deploy/renderer/Dockerfile -t lumina-renderer:1 .`
   Pin the Debian base by digest first and record it in `runtime.lock.json`.
2. Install the unit: copy `deploy/agentai-render.service` to `/etc/systemd/system/`, then `systemctl daemon-reload && systemctl enable --now agentai-render`.
   It reads the cell engine socket from the same wiring file as the browse service.
3. Tell the app: add `AGENTAI_RENDER_SOCKET=/run/agentai-render/render.sock` to `/etc/agentai-platform/accounts.env`.
4. Reinstall `deploy/agentai-tool-relay.service` (its memory limit went from 192M to 512M: it now carries files of up to 50 MB) and restart
   `agentai-platform-app`, `agentai-tool-relay`, `agentai-request-worker` and `agentai-cell-bridge` (the bridge gained `workspace.scan`, `workspace.stat`, `workspace.read`).
5. Cells pick up the new tool and the new rules (`AGENTS.md`, "Giving the customer a file") the next time they start.

## Check it

- `systemctl status agentai-render` shows `render service on /run/agentai-render/render.sock`.
- `/v1/app` reports `"convert": true` under `features`.
- In a chat: "give me a one-page PDF about tea" produces a file card under the answer with a first-page preview. Then "the same as an Excel sheet", "as slides", "as a Word document".
- Formats to try once after the first build, because they need the real converters and are not covered by the test suite:
  Markdown to PDF, DOCX and PPTX; HTML to PDF and PNG; CSV and a JSON sheet description to XLSX; DOCX, XLSX and PPTX to PDF; SVG to PNG; a document with an image in `include`.
  Check a right-to-left and a CJK document too (the image carries Noto fonts for both).

## When something is wrong

| Sign | Cause |
|---|---|
| The assistant says converting is not available | `AGENTAI_RENDER_SOCKET` is not set, or the service is down |
| "The converter is not available" | The image name is wrong or was built into the host engine instead of the cell engine |
| "The conversion took too long" | The 150 second limit; very large spreadsheets or documents |
| Text shows as boxes | A script the image has no font for: add the font package to the Dockerfile and rebuild |

To switch it off: remove `AGENTAI_RENDER_SOCKET` and restart the app and the tool relay. Nothing else depends on it.
