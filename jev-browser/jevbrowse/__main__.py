"""python -m jevbrowse "Order me underwear from youngla.com"   (opens a Chrome window and shows every step here)"""
import argparse
import os

from .browser import Browser
from .goal import HERE, load_env, search_words, start_url
from .jev import Jev
from .log import RunLog
from .loop import run

def main():
    ap = argparse.ArgumentParser(prog='jevbrowse', description='Give a goal; JEV drives a Chrome window until it is done.')
    ap.add_argument('goal', nargs='+', help='what you want done, ideally naming the site (youngla.com)')
    ap.add_argument('--url', help='the page to start on (otherwise taken from the goal, or asked)')
    ap.add_argument('--text', action='append', help='a text JEV may type (repeat for several); default: the useful words of the goal')
    ap.add_argument('--steps', type=int, default=25)
    ap.add_argument('--headless', action='store_true', help='no visible Chrome window')
    ap.add_argument('--no-shots', action='store_true', help='do not save a picture of every page next to the log')
    args = ap.parse_args()
    goal = ' '.join(args.goal)
    load_env(HERE / '.env')
    key = os.environ.get('TYPESAFE_API_KEY', '').strip()
    if not key:
        raise SystemExit('Put TYPESAFE_API_KEY=... in jev-browser/.env')
    url = args.url or start_url(goal) or input('Which page should I start on? (a URL) ').strip()
    texts = args.text or search_words(goal)
    log = RunLog()
    print(f'goal: {goal}\nstart: {url}\nJEV may type: {texts}\nlog: {log.path}')
    browser = Browser(headless=args.headless, log=log, shots_dir=None if args.no_shots else log.shots_dir)
    try:
        status, detail = run(goal, url, browser, Jev(key, log=log), texts, steps=args.steps, log=log)
        print(f'\n{status.upper()}: {detail}')
        if status in ('needs_user', 'password', 'sensitive') and not args.headless:
            input('The browser is yours now. Press Enter here to close it. ')
    except BaseException as exc:
        import traceback
        log.emit('crash', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
        raise
    finally:
        browser.close()
        print(f'full detail of this run: {log.path}\nread it with: .venv/bin/python -m jevbrowse.log')


if __name__ == '__main__':
    main()
