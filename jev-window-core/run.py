#!/usr/bin/env python3
"""Choose a Mac window and run the bare screenshot loop."""
import argparse
from pathlib import Path
import subprocess
import sys

from loop import run
from model import Jev, ModelError, load_key
from native import Controller, NativeError

HERE = Path(__file__).resolve().parent


def build():
    source, binary = HERE / 'Window.swift', HERE / '.build' / 'jev-window'
    if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
        binary.parent.mkdir(exist_ok=True)
        subprocess.run(['swiftc', '-parse-as-library', '-O', str(source), '-o', str(binary)], check=True)
    return binary


def main():
    ap = argparse.ArgumentParser(description='Choose an open Mac window. Prompt -> screenshot -> Jev -> action -> repeat.')
    ap.add_argument('prompt', nargs='?', help='initial instructions; copied to the editable prompt file')
    ap.add_argument('--prompt-file', type=Path, default=HERE / 'prompt.txt', help='editable instructions, reread before every decision and action')
    ap.add_argument('--text', action='append', default=[], help='exact text the model may type; repeat for several choices')
    ap.add_argument('--steps', type=int, default=500)
    ap.add_argument('--delay', type=float, default=.8, help='seconds between actions')
    ap.add_argument('--window', type=int, help='select a window by its current macOS window ID')
    ap.add_argument('--list', action='store_true', help='list windows without contacting Jev')
    ap.add_argument('--build', action='store_true', help='compile the helper only, without accessing windows')
    ap.add_argument('--preview', action='store_true', help='show one model decision without sending any input')
    args = ap.parse_args()
    if args.steps < 1 or not 0 <= args.delay <= 60:
        ap.error('steps must be positive; delay must be between 0 and 60')
    binary = build()
    if args.build:
        print(f'Built {binary}')
        return
    controller = Controller(binary)
    try:
        windows = controller.call('list')['windows']
        if not windows:
            raise NativeError('No capturable windows are open')
        for i, window in enumerate(windows, 1):
            print(f'{i:2}. {window["app"]}: {window["title"] or "(untitled)"}  [ID {window["id"]}]')
        if args.list:
            return
        key = load_key(HERE / '.env')
        if args.window:
            selected = next((w for w in windows if w['id'] == args.window), None)
            if selected is None:
                raise NativeError('That window is not in the current list')
        else:
            try:
                index = int(input('Choose window number: '))
            except ValueError:
                raise NativeError('Enter a number from the window list') from None
            if not 1 <= index <= len(windows):
                raise NativeError('Window number is outside the list')
            selected = windows[index - 1]
        if args.prompt:
            args.prompt_file.write_text(args.prompt + '\n')
        elif not args.prompt_file.exists():
            args.prompt_file.write_text(input('Instructions: ').strip() + '\n')
        prompt_source = lambda: args.prompt_file.read_text()
        if not prompt_source().strip():
            raise NativeError('The prompt file is empty')
        print(f'Instructions: {args.prompt_file}\nEdit that file anytime; clear it to pause. Ctrl-C stops.\n'
              'The selected window must stay in front. Screenshots are sent to TypeSafe/Jev.\n'
              'No screenshots or model requests are saved to disk.')
        input('Press Enter to select the window and start. ')
        controller.call('select', window=selected['id'], pid=selected['pid'])
        status = run(controller, Jev(key), prompt_source, texts=args.text, steps=args.steps,
                     delay=args.delay, dry_run=args.preview)
        print(f'Stopped: {status}')
    finally:
        controller.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped.')
    except (ModelError, NativeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        raise SystemExit(1)

