# Jev window core

The bare loop, extracted from `../jev-browser`: **prompt → selected-window picture → Jev choice → one action → fresh picture**.

No dashboard, DOM reader, Playwright, planner, browser launch, account system, or Python/Node dependencies. It controls an existing Mac window, including a browser window. The small Swift helper is only the window picker/capture/input backend; the Python loop and Jev client are separate.

## Start

Needs macOS 14+, Python 3.10+, and Apple's Swift compiler (Xcode or Command Line Tools).

```sh
cd /Users/parsa/AgentAI/jev-window-core
export TYPESAFE_API_KEY='your-key'
python3 run.py 'Your instructions here'
```

Choose a window number from the printed list. The first run compiles the native helper. Enable **Screen Recording** and **Accessibility** for the terminal/app running it in System Settings if requested, then restart. The program checks permissions but does not grant them or open permission prompts itself.

The selected window comes forward. Jev sees its picture, chooses an action, and gets another picture after the action. Clicking, scrolling in four directions, Return, Escape, waiting, and stopping are supported. To allow typing, supply exact texts with `--text 'search query'` (repeat for multiple choices). It inserts text in the chosen field; it does not clear existing content automatically.

```sh
python3 run.py --list                         # list open capturable windows, no model request
python3 run.py --window 123 'Review this page' # select by current window ID
python3 run.py --preview 'Find the search box' # one decision; no clicks or typing
python3 run.py --build                        # compile only; no window access
python3 -m unittest discover -s tests -v
```

## Ongoing instructions

The prompt lives in `prompt.txt`. **Edit it while running**: the loop rereads it before every model call and before acting. A reply to an outdated prompt is discarded. Clear the file to pause; add instructions and return to the selected window to resume. `--prompt-file /path/to/instructions.txt` uses a different file. Passing a positional prompt deliberately replaces that file's contents; omit it to resume existing instructions.

The last six distinct pictures and twelve recent actions go into the next decision. This is bounded recent visual memory, not permanent memory of every photo. When a new picture is identical, the model is told that scrolling may have reached the end. Three unchanged pictures or three uncertain decisions stop a stuck loop. Default maximum is 500 decisions; change with `--steps`. Ctrl-C stops and terminates the helper. `--delay` sets the settling time between actions (default 0.8 seconds).

An example prompt for the earlier workflow:

> Review at least three distinct photos per profile when available. Prefer natural-looking photos and simple, polished styling. Use regular likes or skip only. Never use Roses, Super Likes, messages, purchases, or upgrades. Scroll for more evidence when unsure; at the end of the profile make a final like or skip decision. After acting, verify a new profile loaded. Stop when the app says the free-like limit is reached. Visual appearance does not establish that an account is genuine.

## Window boundaries and limits

The helper binds the selected **window ID, process, and Accessibility window**. It checks focus and bounds before capture and before input; it never silently switches to a different window. Moving/resizing invalidates the previous picture and triggers a new one. Switching focus pauses until the selected window is active again. Closing/minimizing the window stops with an error. Native input is sent to the selected process, with coordinates computed from the current window frame, never from a hard-coded desktop location.

Some custom windows do not expose sufficient Accessibility information, and menus/dialogs in separate windows are deliberately not followed. Those need you to act or select another window. iPhone Mirroring must remain connected and the iPhone locked; compatibility of its clicks/scrolling still needs a live smoke test. Browser tabs remain part of the selected browser window, so the loop follows what is currently visible in that window.

The model sees screenshots, not page code or extracted text. Pictures are sent to **TypeSafe's Jev API**, using the same model and image request format as the existing browser core. Multiple pictures are included as image assets. No screenshots, prompts, model responses, or actions are logged to disk; only the editable prompt is saved. Avoid selecting windows containing information you do not want sent to that service. Password controls and recognizable payment/destructive/permission controls stop native input; visual instructions also tell the model to hand those steps to the user. These checks are not a guarantee that every sensitive action in every app can be detected.

## Files

- `model.py`: extracted Jev image request and strict answer validation.
- `loop.py`: the reusable loop; accepts any controller with `shot()` / `act()`.
- `Window.swift`, `native.py`: Mac window listing, capture, focus checks and input.
- `run.py`: compile helper, choose window, read prompt, run.
- `tests/test_core.py`: model protocol and loop regression tests with fake controllers; no live model charges or UI actions.

The old browser project is untouched. Setup copied only its `TYPESAFE_API_KEY` into this project's private `.env` (mode 0600); no other credentials were copied. The runtime never loads the old project's environment.
