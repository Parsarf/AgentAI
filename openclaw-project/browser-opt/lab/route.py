"""Which web tool does the assistant reach for first? The same requests, the same model, the three tools as the runtime describes them, and the browser tool's description
as it was (`--old <file with the old description>`) or as it is now. Only the first tool call is judged: reading a page with the browser costs a browser session and a paid
confirmation where web_fetch costs one request, and sending a cart task to web_fetch cannot work at all.

    python3 browser-opt/lab/route.py [--old old-description.txt] [--repeat 2]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lab import Meter, adapter, ask_model, parse_step       # noqa: E402

# The runtime's own words for its two tools (OpenClaw 2026.9.6, openclaw-tools-*.mjs).
WEB_FETCH = 'Fetch URL; extract readable markdown/text. Lightweight; no browser automation.'
WEB_SEARCH = 'Search current web; normalized provider results. Supports freshness and date-range filters (freshness, date_after/date_before) and domain filtering (domain_filter).'
READ, FIND, USE = ('web_fetch', 'web_search'), ('web_search', 'web_fetch'), ('lumina_browser',)
CASES = [
    ('What is the latest released version of the requests library on PyPI?', READ),
    ('Summarize this article: https://en.wikipedia.org/wiki/Ada_Lovelace', ('web_fetch',)),
    ("What are today's top headlines on BBC News?", READ),
    ('Find me three well-reviewed carbon pickleball paddles under $100.', FIND),
    ('How many stars does https://github.com/microsoft/playwright have?', ('web_fetch',)),
    ('What does this page say? https://news.ycombinator.com/', ('web_fetch',)),
    ('Read https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/at and tell me what at() returns for an index that is out of range.', ('web_fetch',)),
    ("What's the weather in Irvine tomorrow?", FIND),
    ('Compare the price of AirPods Pro at Best Buy and at Target.', FIND),
    ('Who won the 2026 Tour de France?', FIND),
    ('Add a pair of black joggers in size Medium from youngla.com to my cart.', USE),
    ('Fill in the contact form on https://www.example-clinic.com/contact with my name, Jordan Lee, and ask for a Tuesday appointment. Do not send it yet.', USE),
    ("Check what is in my Amazon cart right now.", USE),
    ('Look up flights from Zurich to London on 20 December on Google Flights and tell me the cheapest.', USE),
    ('Find a table for two at 7pm tonight at Nobu on OpenTable and stop before booking.', USE),
    ("Search Zara's own site for linen shirts and tell me which sizes are in stock for the first one.", USE),
    ('On DoorDash, find the three spiciest chicken dishes that deliver to 92618.', USE),
    ('Sign in to my Canvas at canvas.eee.uci.edu and list my assignments due this week.', USE),
]


def system(browser_description):
    tools = [{'name': 'web_search', 'description': WEB_SEARCH}, {'name': 'web_fetch', 'description': WEB_FETCH}, {'name': 'lumina_browser', 'description': browser_description}]
    return ('You are a helpful assistant with these tools:\n' + json.dumps(tools, indent=1) + '\n\nFor the request you are given, reply with ONLY a JSON object naming the FIRST tool '
            'you would call and why: {"tool": "<name>", "why": "<one short sentence>"}. Use {"tool": "none"} only if no tool is needed.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--old', default='')
    parser.add_argument('--repeat', type=int, default=1)
    args = parser.parse_args()
    variants = {'now': adapter.TOOL['description']}
    if args.old:
        variants = {'before': Path(args.old).read_text().strip(), **variants}
    meter = Meter()
    for name, description in variants.items():
        right, rows = 0, []
        for request, wanted in CASES:
            for _ in range(args.repeat):
                answer = parse_step(ask_model(system(description), request, meter)) or {}
                ok = answer.get('tool') in wanted
                right += ok
                rows.append((ok, answer.get('tool'), wanted, request))
        print(f'== {name}: {right}/{len(rows)} first calls went to a fitting tool')
        for ok, tool, wanted, request in rows:
            if not ok:
                print(f'   chose {tool}, fitting {"/".join(wanted)}: {request[:90]}')
    print(f'({meter.calls} model calls)')


if __name__ == '__main__':
    main()
