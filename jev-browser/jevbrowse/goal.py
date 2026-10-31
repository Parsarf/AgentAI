"""Turning a goal into a start page and the words worth typing, and reading .env. Shared by the command line and the dashboard."""
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
URL = re.compile(r'https?://[^\s<>"\')]+', re.I)
DOMAIN = re.compile(r'\b((?:[a-z0-9-]+\.)+(?:com|org|net|co|io|shop|store|us|uk|ca|de|fr|ai|app))\b', re.I)
FILLER = set('a an the my me i we you please can could would will to for from on in at of and or with some any one pair new order buy purchase get find search '
             'look show add put cart bag basket checkout want need like go open visit website site store shop page online'.split())


def load_env(path):
    try:
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))
    except OSError:
        pass


def start_url(goal):
    m = URL.search(goal)
    if m:
        return m.group(0).rstrip('.,;')
    m = DOMAIN.search(goal)
    return f'https://{m.group(1).lower()}/' if m else ''


def search_words(goal):
    """The goal without verbs, filler and the site name: what is worth typing into a search box."""
    goal = DOMAIN.sub(' ', URL.sub(' ', goal))
    words = [w for w in re.findall(r"[A-Za-z0-9'-]+", goal) if w.lower() not in FILLER]
    return [' '.join(words[:4])] if words else []
