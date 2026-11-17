# UI remodel: how it is built

Working notes for the six phases (the prompts were removed once all six phases were live). The per-phase status files sit beside this one.

## Shape

- `components/frame/FrameProvider.tsx` (in `Shell`) owns the width class, zone widths (remembered per person), which zones are docked or sheets, and the open state of the context column, the inspector and the assistant.
- `Shell` grid: **rail** | **workspace** | **assistant**. The page renders `<Workspace>` (components/frame/Workspace.tsx), whose grid is **context** | **canvas** | **inspector**. A page never writes a grid of its own.
- The document scrolls (Chat relies on window scroll: stick to bottom, jump to latest, sticky composer). Rail, context, inspector and assistant are sticky, full-height columns with their own scroll. A page with fixed panes (Inbox, Calendar, Files) passes `fill`: the canvas is then the height of the window and scrolls inside.
- Width classes: `compact` < 600 (bottom bar, one zone at a time, every side zone a sheet), `medium` 600-1199 (rail, context, canvas; inspector and assistant sheets), `expanded` 1200-1499 (inspector docked), `large` >= 1500 (all docked). The canvas keeps its minimum: if docked zones would push it under, the assistant, then the inspector, then the context become sheets.
- The assistant panel is one shared thing (`components/frame/Assistant.tsx`, state in `AssistantProvider`): pages say what is selected with `useSelection({ looking, words, actions })`. Its messages go to `POST /v1/assistant/ask`, which checks every id on the server.
- The command bar (`components/frame/CommandBar.tsx`) and the help sheet read one registry (`lib/shortcuts.ts`). Search goes through `GET /v1/search`.

## Decisions taken while building (owner asked for research-and-decide)

- **No `ui_v2` switch in the shipped code.** The README planned a switch so phases could reach the live site one by one with the old layout kept until phase 6. The owner then asked for all six phases to ship in one deploy, together with #52, and phase 6 deletes the switch. A switch that exists in no deployed version protects nothing, so the frame replaces the old shell directly; the old-versus-new comparison was done locally with screenshots of the pre-remodel build (status files).
- **Hand-written virtualizer**, fixed row heights per density (rule 6 allowed one small library; a fixed-height window is about 60 lines and needs none).
- **Canvas surface**: the rail and the context column sit on `--surface-base` (the darkest step); the canvas, inspector and assistant are panels on `--surface-canvas` (the old sidebar's value); cards inside stay `--surface`. Every old value is kept; the order of the steps is what changed (decision 3).
