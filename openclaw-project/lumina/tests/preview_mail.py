"""Local preview of the mail experience on the REAL server code, for looking at it and driving it in a browser. Test fixture only: never deployed, accepts no real account.

    cd lumina && npm run build && ../platform/.venv/bin/python tests/preview_mail.py          -> https://127.0.0.1:5183/app/inbox   (a self-signed certificate)
    node tests/mail-browser.mjs                                                               the real-browser checks against it

What is real: the whole account application (accounts/, its middleware and its content policies, the app shell serving `dist/`), the connector service and its custody,
the sign-in routes, the sync engine, the mail service and what it does to a message before it is shown, the action pipeline that sends and organizes, and the two
provider adapters themselves (the code that speaks Gmail's and Microsoft Graph's protocols).

What stands in, HERE ONLY: the two mail services. Each is the HTTP-level fake its adapter's own tests use (tests/test_google_hub.py, tests/test_microsoft_hub.py), filled
with mail made to look like the mail people get: plain text, a reply written in a web mail program, one from a desktop mail program, a newsletter, a receipt, pictures
carried inside a message, attachments, a long thread, right-to-left text, and a message that tries everything a message must not be able to do. Their sign-in pages are a
page of this fixture that offers each way a sign-in can end. Nothing here is a claim about the real services: that needs a real account (platform/deploy/phase6_*_live.py).

The browser signs in as the one synthetic customer below.
"""
from __future__ import annotations
import base64
import json
import os
import secrets
import shutil
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT.parent / 'platform'
sys.path.insert(0, str(PLATFORM))
PORT = int(os.environ.get('PREVIEW_PORT', '5183'))
ORIGIN = f'https://127.0.0.1:{PORT}'
EMAIL, PASSWORD = 'mail-preview@example.invalid', 'Mail-Preview-2026!'
STATE = tempfile.mkdtemp(prefix='lumina-mail-preview-')
os.chmod(STATE, 0o700)
os.environ.update({'AGENTAI_STATE_DIR': STATE, 'AGENTAI_SESSION_SECRET': secrets.token_urlsafe(48), 'AGENTAI_PUBLIC_ORIGIN': ORIGIN, 'DJANGO_SETTINGS_MODULE': 'accounts.settings',
                   'AGENTAI_UI_BUNDLE_DIR': str(ROOT / 'dist'), 'AGENTAI_CONNECTOR_KEY_FILE': str(Path(STATE) / 'connector.key')})
os.chdir(PLATFORM)

from agentai_platform.vault import Keyring                                        # noqa: E402
with open(os.open(os.environ['AGENTAI_CONNECTOR_KEY_FILE'], os.O_WRONLY | os.O_CREAT, 0o600), 'w') as handle:
    handle.write(Keyring.generate() + '\n')

import django                                                                     # noqa: E402
django.setup()
from django.core.management import call_command                                   # noqa: E402
from django.core.wsgi import get_wsgi_application                                 # noqa: E402
from django.db import connection, connections                                     # noqa: E402
import contextlib                                                                 # noqa: E402
import uuid                                                                       # noqa: E402

with open(os.devnull, 'w') as devnull, contextlib.redirect_stdout(devnull):
    call_command('bootstrap_accounts', verbosity=0)
from accounts import wiring                                                       # noqa: E402
from accounts.services import consume, create_invite                              # noqa: E402
from agentai_platform import google_hub, hub_model, microsoft_hub                 # noqa: E402
from agentai_platform.connector_kit import ProviderError                          # noqa: E402
from tests.test_google_hub import FakeGoogle, b64                                 # noqa: E402
from tests.test_microsoft_hub import FakeGraph, jwt                               # noqa: E402

ACCOUNT = 'mail-preview'
with connection.cursor() as c:
    c.execute("INSERT INTO accounts(id,status) VALUES (%s,'active')", [ACCOUNT])
user, raw_invite = create_invite(EMAIL, ACCOUNT, 'fixture', uuid.uuid4())
consume(raw_invite, 'onboarding', PASSWORD, uuid.uuid4())
with connection.cursor() as c:
    c.execute('INSERT INTO projects(account_id,id,name) VALUES (%s,%s,%s)', [ACCOUNT, 'preview-project', 'Preview project'])
    c.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (%s,'preview-deployment',1,'stopped')", [ACCOUNT])
connections.close_all()

NOW = int(time.time())
MIN, HOUR, DAY = 60, 3600, 86400
ME_G, ME_M = 'dana.reyes@gmail.test', 'dana@outlook.test'
SEEN = []                                                                         # every remote picture a browser asked this fixture for: (name, query)


# -- small pictures, made here (no file is read) ----------------------------------------------------------------------------------------------------------
def png(width, height, rgb) -> bytes:
    row = b'\x00' + bytes(rgb) * width
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(row * height, 9)) + chunk(b'IEND', b'')


PICTURES = {'hero': png(600, 220, (36, 99, 235)), 'logo': png(120, 36, (17, 24, 39)), 'product': png(160, 160, (234, 179, 8)), 'pixel': png(1, 1, (255, 255, 255)),
            'avatar': png(48, 48, (16, 185, 129))}
CHART = png(420, 180, (99, 102, 241))
SCREEN = png(360, 200, (30, 41, 59))
PDF = b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n'


def remote(name, message) -> str:
    return f'{ORIGIN}/fake/picture/{name}.png?m={message}'


# -- the mail ------------------------------------------------------------------------------------------------------------------------------------------------
NEWSLETTER = lambda mid: f'''<html><head><meta name="viewport" content="width=device-width"><style>
body{{margin:0;background:#f3f4f6}} .wrap{{width:600px;max-width:100%}} .btn a{{background:#2563eb;color:#ffffff !important;text-decoration:none;padding:12px 22px;border-radius:6px;display:inline-block;font-weight:bold}}
h1{{font-family:Georgia,serif;font-size:26px;color:#111827;margin:0 0 12px}} p{{font-family:Helvetica,Arial,sans-serif;font-size:15px;line-height:22px;color:#374151}}
.muted{{color:#6b7280;font-size:12px}} @media (max-width:620px){{.wrap{{width:100% !important}} h1{{font-size:22px !important}}}}
@import url("{ORIGIN}/fake/picture/pixel.png?m={mid}-import");
</style></head><body bgcolor="#f3f4f6"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#f3f4f6"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" class="wrap" width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;overflow:hidden">
<tr><td style="padding:20px 28px"><img src="{remote('logo', mid)}" width="120" height="36" alt="Northwind Weekly" style="display:block"></td></tr>
<tr><td><img src="{remote('hero', mid)}" width="600" alt="Autumn collection" style="display:block;width:100%;height:auto"></td></tr>
<tr><td style="padding:28px"><h1>The autumn edit is here</h1><p>Twelve new pieces, made in small batches. Members get early access until Sunday, and free returns on everything.</p>
<table role="presentation" cellpadding="0" cellspacing="0" class="btn"><tr><td><a href="https://northwind.example/autumn?utm=weekly">Shop the collection</a></td></tr></table>
<p style="margin-top:24px"><b>Also this week</b></p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td width="50%" valign="top" style="padding-right:8px"><img src="{remote('product', mid)}" width="160" height="160" alt="Wool scarf"><p>Wool scarf<br><span class="muted">$48</span></p></td>
<td width="50%" valign="top" style="padding-left:8px"><img src="{remote('product', mid)}" width="160" height="160" alt="Canvas tote"><p>Canvas tote<br><span class="muted">$32</span></p></td></tr></table></td></tr>
<tr><td style="padding:18px 28px;background:#111827"><p class="muted" style="color:#9ca3af">You get this because you joined Northwind Weekly. <a href="https://northwind.example/unsubscribe" style="color:#9ca3af">Unsubscribe</a></p></td></tr>
</table><img src="{remote('pixel', mid)}" width="1" height="1" alt=""></td></tr></table></body></html>'''

RECEIPT = lambda mid: f'''<div style="background-color:#ffffff;font-family:-apple-system,Helvetica,Arial,sans-serif;color:#111111;max-width:560px;margin:0 auto;padding:24px">
<img src="{remote('logo', mid)}" width="120" height="36" alt="Fennel Market">
<h2 style="font-size:20px;margin:20px 0 4px">Receipt for order #48213</h2><p style="color:#555555;margin:0 0 16px">Paid on November 20, 2026 with Visa ending 4242</p>
<table width="100%" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-size:14px">
<tr style="background:#f6f6f6"><th align="left">Item</th><th align="right">Qty</th><th align="right">Price</th></tr>
<tr><td style="border-bottom:1px solid #eeeeee">Sourdough loaf</td><td align="right" style="border-bottom:1px solid #eeeeee">2</td><td align="right" style="border-bottom:1px solid #eeeeee">$14.00</td></tr>
<tr><td style="border-bottom:1px solid #eeeeee">Olive oil, 500 ml</td><td align="right" style="border-bottom:1px solid #eeeeee">1</td><td align="right" style="border-bottom:1px solid #eeeeee">$18.50</td></tr>
<tr><td style="border-bottom:1px solid #eeeeee">Delivery</td><td align="right" style="border-bottom:1px solid #eeeeee"></td><td align="right" style="border-bottom:1px solid #eeeeee">$4.00</td></tr>
<tr><td><b>Total</b></td><td></td><td align="right"><b>$36.50</b></td></tr></table>
<p style="font-size:12px;color:#777777;margin-top:20px">Questions? Reply to this email or visit <a href="https://fennel.example/help">fennel.example/help</a>.</p></div>'''

WEB_REPLY = '''<div dir="ltr">Thursday works. Noon at the usual place?<div><br></div><div>I will bring the contract so we can go through section 4 together.</div></div><br>
<div class="gmail_quote gmail_quote_container"><div dir="ltr" class="gmail_attr">On Wed, Nov 18, 2026 at 9:12 AM Ada Park &lt;ada.park@example.com&gt; wrote:<br></div>
<blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex;border-left:1px solid rgb(204,204,204);padding-left:1ex"><div dir="ltr">Are you free for lunch on Thursday? I would like to talk about the contract before it goes out.</div></blockquote></div>'''

DESKTOP_REPLY = '''<html xmlns:o="urn:schemas-microsoft-com:office:office"><head><meta name="Generator" content="Microsoft Word 15"><style><!--
/* Font Definitions */ @font-face {font-family:Calibri; panose-1:2 15 5 2 2 2 4 3 2 4;}
p.MsoNormal, li.MsoNormal, div.MsoNormal {margin:0in; font-size:11.0pt; font-family:"Calibri",sans-serif; color:black;}
a:link, span.MsoHyperlink {color:#0563C1; text-decoration:underline;}
--></style></head><body lang="EN-US" link="#0563C1" vlink="#954F72" style="word-wrap:break-word">
<div class="WordSection1"><p class="MsoNormal">Hi Dana,<o:p></o:p></p><p class="MsoNormal"><o:p>&nbsp;</o:p></p>
<p class="MsoNormal">The numbers are attached. Two things to look at before Friday:<o:p></o:p></p>
<p class="MsoNormal"><span style="color:#C00000"><b>1. Travel is 18% over budget.</b></span><o:p></o:p></p>
<p class="MsoNormal"><span style="color:#1F3864">2. Renewals closed a week early, see <a href="https://intranet.example/q3">the Q3 page</a>.</span><o:p></o:p></p>
<p class="MsoNormal"><o:p>&nbsp;</o:p></p><p class="MsoNormal">Best,<br>Ben<o:p></o:p></p><p class="MsoNormal"><o:p>&nbsp;</o:p></p>
<div><div style="border:none;border-top:solid #E1E1E1 1.0pt;padding:3.0pt 0in 0in 0in"><p class="MsoNormal"><b>From:</b> Dana Reyes &lt;dana.reyes@gmail.test&gt;<br><b>Sent:</b> Thursday, November 19, 2026 4:02 PM<br>
<b>To:</b> Ben Ortiz &lt;ben.ortiz@example.com&gt;<br><b>Subject:</b> Quarterly numbers for review<o:p></o:p></p></div></div>
<p class="MsoNormal"><o:p>&nbsp;</o:p></p><p class="MsoNormal">Could you send the quarterly numbers before Friday? I need them for the board pack.<o:p></o:p></p></div></body></html>'''

INLINE = '''<div dir="ltr">Here is the chart from this morning, and the full deck is attached.<br><br><img src="cid:ii_chart01" alt="Weekly active accounts" width="420" height="180"><br><br>
The dip on the 12th is the outage. Everything after it is back on trend.</div>'''

HOSTILE = lambda mid: f'''<div onclick="steal()" onmouseover="steal()">Security notice<script>document.title='SCRIPT-RAN';fetch('{ORIGIN}/fake/picture/pixel.png?m={mid}-script')</script>
<img src="x" onerror="document.title='ONERROR-RAN'"><iframe src="{ORIGIN}/fake/picture/pixel.png?m={mid}-iframe"></iframe>
<form action="{ORIGIN}/fake/picture/pixel.png" method="post"><input name="password" placeholder="Your password"><button>Confirm</button></form>
<a href="javascript:document.title='JS-LINK-RAN'" id="js-link">Verify your account</a> <a href="https://phish.example/login" id="real-link">Open the portal</a>
<meta http-equiv="refresh" content="0;url={ORIGIN}/fake/picture/pixel.png?m={mid}-refresh"><link rel="stylesheet" href="{ORIGIN}/fake/picture/pixel.png?m={mid}-link">
<p style="background:url({ORIGIN}/fake/picture/pixel.png?m={mid}-css);width:expression(alert(1));position:fixed;top:0;left:0">Styled paragraph</p>
<style>@import url("{ORIGIN}/fake/picture/pixel.png?m={mid}-import"); body{{background:url("{ORIGIN}/fake/picture/pixel.png?m={mid}-sheet")}} @font-face{{font-family:x;src:url("{ORIGIN}/fake/picture/pixel.png?m={mid}-font")}}</style>
<svg onload="document.title='SVG-RAN'"><script>document.title='SVG-SCRIPT-RAN'</script></svg><object data="{ORIGIN}/fake/picture/pixel.png?m={mid}-object"></object>
<img src="{remote('pixel', mid + '-img')}" width="1" height="1"></div>'''

COLOURS = '''<div><p><span style="color:rgb(0,0,0)">Black text set by the sender.</span></p><p><font color="#000080">Navy text in an old font tag.</font></p>
<p><span style="color:#c00000"><b>Dark red, important.</b></span> <span style="color:#38761d">Green, approved.</span> <span style="color:#ffffff">White text (hidden on a light page).</span></p>
<p><span style="font-family:Georgia,serif;font-size:18px">A serif heading the sender chose</span></p>
<ul><li>First point</li><li>Second point with a <a href="https://example.com/doc">link</a></li></ul>
<table border="1" cellpadding="6" style="border-collapse:collapse"><tr><th>Day</th><th>Hours</th></tr><tr><td>Monday</td><td>6.5</td></tr><tr><td>Tuesday</td><td>7</td></tr></table></div>'''

RTL = '<div dir="rtl" lang="fa" style="font-size:15px">سلام دانا،<br><br>جلسهٔ فردا ساعت ۱۰ صبح برگزار می‌شود. لطفاً گزارش را همراه داشته باشید.<br><br>با احترام،<br>سارا</div>'

LONG_SUBJECT = 'Re: Fwd: [Northwind/platform] Proposal to move the quarterly planning review to the second week of December and merge it with the budget sign-off (#4821)'

SENDERS = [('Ada Park', 'ada.park@example.com'), ('Ben Ortiz', 'ben.ortiz@example.com'), ('Chen Wei', 'chen.wei@example.com'), ('Dana Ruiz', 'druiz@fieldnotes.example'),
           ('Eli Novak', 'eli@novak.example'), ('Fay Osei', 'fay.osei@example.com'), ('Gus Lind', 'gus@lind.example'), ('Hana Sato', 'hana.sato@example.com'),
           ('Ivo Marsh', 'ivo@marsh.example'), ('Jo Keller', 'jo.keller@example.com')]
TOPICS = ['Notes from the offsite', 'Your flight to Lisbon is confirmed', 'Invoice 2031 is ready', 'Question about the API limits', 'Welcome aboard', 'Design feedback, round two',
          'Parking permit renewal', 'Minutes of the residents meeting', 'Photos from Saturday', 'Reminder: dentist on the 3rd', 'Draft agenda for Monday', 'Your statement is available']


class PreviewGoogle(FakeGoogle):
    """The Gmail fake of the adapter's own tests, with mail that looks like mail and with attachments that can be read."""
    def __init__(self):
        super().__init__(email=ME_G, now=NOW)
        self.labels += [{'id': 'Label_9', 'name': 'Receipts', 'type': 'user'}, {'id': 'TRASH', 'name': 'TRASH', 'type': 'system'}, {'id': 'SPAM', 'name': 'SPAM', 'type': 'system'},
                        {'id': 'DRAFT', 'name': 'DRAFT', 'type': 'system'}]
        self.files, self.n = {}, 0
        self.scope += ' ' + ' '.join(g.scope for g in google_hub.GRANTS)        # the fixture's customer has already allowed changes (sending, organizing, the calendar)
        self.fill()

    def add(self, sender, subject, *, text=None, html=None, thread=None, labels=('INBOX',), ago=HOUR, files=(), inline=(), to=None, cc=None, snippet=None):
        self.n += 1
        mid = f'g{self.n:04d}'
        parts = []
        if text is not None:
            parts.append({'mimeType': 'text/plain', 'body': {'data': b64(text)}})
        if html is not None:
            parts.append({'mimeType': 'text/html', 'body': {'data': b64(html(mid) if callable(html) else html)}})
        for cid, kind, data in inline:
            aid = f'{mid}-in-{cid}'; self.files[(mid, aid)] = data
            parts.append({'mimeType': kind, 'filename': '', 'headers': [{'name': 'Content-ID', 'value': f'<{cid}>'}, {'name': 'Content-Disposition', 'value': 'inline'}], 'body': {'attachmentId': aid, 'size': len(data)}})
        for name, kind, data in files:
            aid = f'{mid}-at-{len(parts)}'; self.files[(mid, aid)] = data
            parts.append({'mimeType': kind, 'filename': name, 'body': {'attachmentId': aid, 'size': len(data)}})
        who = sender if isinstance(sender, str) else f'{sender[0]} <{sender[1]}>'
        heads = [{'name': 'From', 'value': who}, {'name': 'To', 'value': to or f'Dana Reyes <{ME_G}>'}, {'name': 'Subject', 'value': subject},
                 {'name': 'Date', 'value': datetime.fromtimestamp(NOW - ago, timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')}, {'name': 'Message-ID', 'value': f'<{mid}@mail.example>'}]
        if cc:
            heads.append({'name': 'Cc', 'value': cc})
        plain = snippet or (text or '').replace('\n', ' ')[:160] or 'Open to read this message.'
        self.messages[mid] = {'id': mid, 'threadId': thread or mid, 'labelIds': list(labels), 'snippet': plain, 'internalDate': str((NOW - ago) * 1000),
                              'payload': {'mimeType': 'multipart/mixed', 'headers': heads, 'parts': parts}}
        self.note('messagesAdded', mid)
        return mid

    def fill(self):
        me = f'Dana Reyes <{ME_G}>'
        first = self.add(SENDERS[0], 'Lunch on Thursday?', text='Are you free for lunch on Thursday? I would like to talk about the contract before it goes out.\n\nAda', ago=2 * DAY, labels=('INBOX',))
        self.add(me, 'Re: Lunch on Thursday?', html=WEB_REPLY, text='Thursday works. Noon at the usual place?', thread=first, ago=2 * DAY - 2 * HOUR, labels=('SENT',), to='Ada Park <ada.park@example.com>',
                 snippet='Thursday works. Noon at the usual place? I will bring the contract so we can go through section 4 together.')
        self.add(SENDERS[0], 'Re: Lunch on Thursday?', thread=first, ago=40 * MIN, labels=('INBOX', 'UNREAD'),
                 text='Perfect, noon it is. I booked the table by the window.\n\nOn Wed, Nov 18, 2026 at 11:20 AM Dana Reyes <dana.reyes@gmail.test> wrote:\n> Thursday works. Noon at the usual place?\n>\n'
                      '> I will bring the contract so we can go through section 4 together.\n>\n> On Wed, Nov 18, 2026 at 9:12 AM Ada Park wrote:\n>> Are you free for lunch on Thursday?\n')
        self.add(('Northwind Weekly', 'news@northwind.example'), 'The autumn edit is here', html=NEWSLETTER, ago=3 * HOUR, labels=('INBOX', 'UNREAD', 'CATEGORY_UPDATES'),
                 snippet='Twelve new pieces, made in small batches. Members get early access until Sunday.')
        self.add(('Fennel Market', 'orders@fennel.example'), 'Receipt for order #48213', html=RECEIPT, ago=26 * HOUR, labels=('INBOX', 'Label_9'), snippet='Paid on November 20, 2026 with Visa ending 4242. Total $36.50')
        numbers = self.add(me, 'Quarterly numbers for review', text='Could you send the quarterly numbers before Friday? I need them for the board pack.', ago=3 * DAY, labels=('SENT',), to='Ben Ortiz <ben.ortiz@example.com>')
        self.add(SENDERS[1], 'RE: Quarterly numbers for review', html=DESKTOP_REPLY, thread=numbers, ago=5 * HOUR, labels=('INBOX', 'UNREAD', 'STARRED', 'Label_7'),
                 files=[('Q3 numbers.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', b'PK\x03\x04 a spreadsheet' * 400), ('Board pack draft.pdf', 'application/pdf', PDF)],
                 snippet='Hi Dana, The numbers are attached. Two things to look at before Friday: 1. Travel is 18% over budget.')
        self.add(SENDERS[2], 'Chart from this morning', html=INLINE, ago=7 * HOUR, labels=('INBOX',), inline=[('ii_chart01', 'image/png', CHART)],
                 files=[('Growth deck.pdf', 'application/pdf', PDF), ('Screenshot 2026-11-21.png', 'image/png', SCREEN)], snippet='Here is the chart from this morning, and the full deck is attached.')
        self.add(('Account Security', 'no-reply@secure-login.example'), 'Action required: verify your account', html=HOSTILE, ago=9 * HOUR, labels=('INBOX', 'UNREAD'), snippet='Security notice. Verify your account.')
        self.add(SENDERS[4], 'Colours and a table', html=COLOURS, ago=11 * HOUR, labels=('INBOX',), snippet='Black text set by the sender. Navy text in an old font tag.')
        self.add(('سارا احمدی', 'sara@ahmadi.example'), 'جلسهٔ فردا', html=RTL, ago=13 * HOUR, labels=('INBOX', 'UNREAD'), snippet='سلام دانا، جلسهٔ فردا ساعت ۱۰ صبح برگزار می‌شود.')
        self.add(SENDERS[5], LONG_SUBJECT, text='Agreed. Moving it also frees the room for the hiring panel.\n\nFay', ago=15 * HOUR, labels=('INBOX',),
                 to=f'{me}, Chen Wei <chen.wei@example.com>, Gus Lind <gus@lind.example>, Hana Sato <hana.sato@example.com>', cc='Ivo Marsh <ivo@marsh.example>, Jo Keller <jo.keller@example.com>')
        long = None
        for i in range(8):                                                       # a long conversation, alternating
            who = SENDERS[3] if i % 2 == 0 else me
            mid = self.add(who, ('Re: ' if i else '') + 'Field notes: the survey', thread=long, ago=4 * DAY - i * 5 * HOUR, labels=('SENT',) if who == me else ('INBOX',),
                           to='Dana Ruiz <druiz@fieldnotes.example>' if who == me else None,
                           text=f'Part {i + 1}. ' + 'The survey closed with 412 answers, and the open questions are worth reading in full. ' * (2 + i % 3) + ('\n\nDana' if who == me else '\n\nDana R.'))
            long = long or mid
        for i in range(46):                                                      # enough to scroll, search and select
            who, topic = SENDERS[i % len(SENDERS)], TOPICS[i % len(TOPICS)]
            marks = ['INBOX'] + (['UNREAD'] if i % 5 == 0 else []) + (['STARRED'] if i % 9 == 0 else []) + (['Label_9'] if 'Invoice' in topic or 'statement' in topic else [])
            self.add(who, topic + (f' ({i // len(TOPICS) + 1})' if i >= len(TOPICS) else ''), ago=5 * DAY + i * 7 * HOUR, labels=marks,
                     text=f'Hello Dana,\n\n{topic}. This is a short message with a couple of lines so the preview has something to show.\n\nRegards,\n{who[0]}',
                     files=[('Invoice 2031.pdf', 'application/pdf', PDF)] if 'Invoice' in topic else ())
        self.add(SENDERS[6], 'An old thread, archived', text='Archived a while ago.', ago=20 * DAY, labels=())
        self.add(('Lottery Office', 'winner@prize.example'), 'You have won', text='Claim now.', ago=6 * DAY, labels=('SPAM',))
        self.add(SENDERS[7], 'Deleted last week', text='In the bin.', ago=8 * DAY, labels=('TRASH',))

    def __call__(self, method, url, headers, data=None):
        parts = urlsplit(url)
        if '/attachments/' in parts.path and method == 'GET':
            self.calls.append((method, parts.netloc + parts.path))
            if headers.get('Authorization') != 'Bearer ' + self.access:
                return self._error(401, 'authError')
            mid, aid = parts.path.split('/messages/')[1].split('/attachments/')
            found = self.files.get((mid, aid))
            return self._ok({'size': len(found), 'data': base64.urlsafe_b64encode(found).decode()}) if found is not None else self._error(404, 'notFound')
        known = set(self.messages)
        answer = super().__call__(method, url, headers, data)
        # As the real service does, and the tests' fake does not: a change of labels and a sent message are both in the account's history, which is how Lumina's copy
        # learns of them.
        if method == 'POST' and '/users/me/threads/' in parts.path and answer[0] == 200:
            thread = parts.path.split('/users/me/threads/')[1].split('/')[0]
            for m in self.messages.values():
                if m['threadId'] == thread:
                    self.note('labelsAdded', m['id'])
        for mid in set(self.messages) - known:
            self.note('messagesAdded', mid)
        return answer

    def _token(self, form):
        if form['grant_type'] == 'authorization_code':
            if form.get('code') != 'good-code' or not form.get('code_verifier'):
                return self._error(400, 'invalid_grant', oauth=True)
            claims = b64(json.dumps({'email': self.email, 'email_verified': True, 'iss': 'https://accounts.google.com'}))
            return self._ok({'access_token': self.access, 'refresh_token': self.refresh, 'expires_in': 3599, 'scope': self.scope, 'token_type': 'Bearer', 'id_token': f'h.{claims}.s'})
        return self._ok({'access_token': self.access, 'expires_in': 3599, 'scope': self.scope, 'token_type': 'Bearer'})


class PreviewGraph(FakeGraph):
    """The Microsoft Graph fake of the adapter's own tests, answering a sign-in as Microsoft does and holding mail that looks like mail."""
    def __init__(self):
        super().__init__()
        self.scope = 'openid profile email https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Calendars.Read https://graph.microsoft.com/User.Read'
        self.bodies, self.attached, self.messages, self.events = {}, {}, {}, {}
        stamp = lambda ago: datetime.fromtimestamp(NOW - ago, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        person = lambda name, address: {'emailAddress': {'name': name, 'address': address}}

        def add(mid, conversation, sender, subject, html, *, ago, folder='f-in', read=True, flagged=False, preview='', attachments=(), categories=()):
            self.messages[mid] = {'id': mid, 'conversationId': conversation, 'subject': subject, 'from': person(*sender), 'toRecipients': [person('Dana Reyes', ME_M)], 'ccRecipients': [],
                                  'receivedDateTime': stamp(ago), 'bodyPreview': preview or subject, 'isRead': read, 'flag': {'flagStatus': 'flagged' if flagged else 'notFlagged'},
                                  'hasAttachments': any(not a.get('isInline') for a in attachments), 'parentFolderId': folder, 'categories': list(categories)}
            self.bodies[mid] = html
            self.attached[mid] = list(attachments)
        add('o1', 'oc1', ('Mira Castell', 'mira@castell.example'), 'Lease renewal: the signed copy', ago=90 * MIN, read=False, preview='Attached is the signed copy of the renewal. The new term starts on January 1.',
            html='<div style="font-family:Aptos,Calibri,sans-serif;font-size:12pt;color:rgb(0,0,0)">Hi Dana,</div><div style="font-family:Aptos,Calibri,sans-serif;font-size:12pt;color:rgb(0,0,0)"><br></div>'
                 '<div style="font-family:Aptos,Calibri,sans-serif;font-size:12pt;color:rgb(0,0,0)">Attached is the signed copy of the renewal. The new term starts on January 1.</div>'
                 '<div><br></div><div id="Signature"><img src="cid:sig-logo@castell" width="48" height="48" alt="Castell Property"><br><span style="font-size:10pt;color:rgb(96,94,92)">Mira Castell · Castell Property</span></div>',
            attachments=[{'id': 'o1-a', 'name': 'Lease renewal (signed).pdf', 'contentType': 'application/pdf', 'size': len(PDF), 'isInline': False, 'bytes': PDF},
                         {'id': 'o1-i', 'name': 'logo.png', 'contentType': 'image/png', 'size': len(PICTURES['avatar']), 'isInline': True, 'contentId': 'sig-logo@castell', 'bytes': PICTURES['avatar']}])
        add('o2', 'oc2', ('Orchard School', 'office@orchard.example'), 'Winter concert: tickets and times', NEWSLETTER('o2'), ago=6 * HOUR, read=False, flagged=True,
            preview='The winter concert is on December 12. Two tickets per family are reserved until Friday.', categories=('Family',))
        add('o3', 'oc3', ('Tomas Brandt', 'tomas@brandt.example'), 'Re: Saturday hike', ago=22 * HOUR, preview='Count me in. I can drive if we leave before eight.',
            html='<div>Count me in. I can drive if we leave before eight.</div><div id="appendonsend"></div><hr style="display:inline-block;width:98%" tabindex="-1">'
                 '<div id="divRplyFwdMsg" dir="ltr"><font face="Calibri, sans-serif" style="font-size:11pt" color="#000000"><b>From:</b> Dana Reyes &lt;dana@outlook.test&gt;<br><b>Sent:</b> Friday, November 20, 2026 6:14 PM<br>'
                 '<b>To:</b> Tomas Brandt<br><b>Subject:</b> Saturday hike</font><div>&nbsp;</div></div><div>Who is in for Saturday? The forecast is clear until the afternoon.</div>')
        add('o4', 'oc4', ('Dana Reyes', ME_M), 'Saturday hike', '<div>Who is in for Saturday? The forecast is clear until the afternoon.</div>', ago=28 * HOUR, folder='f-sent', preview='Who is in for Saturday?')
        add('o5', 'oc5', ('City Utilities', 'billing@utilities.example'), 'Your November statement', RECEIPT('o5'), ago=3 * DAY, folder='f-proj', preview='Your statement for November is ready.')
        add('o6', 'oc6', ('Tomas Brandt', 'tomas@brandt.example'), 'Old plans', '<p>Archived plans.</p>', ago=9 * DAY, folder='f-arch', preview='Archived plans.')

    def __call__(self, method, url, headers, data=None):
        parts = urlsplit(url)
        path = parts.path.replace('/v1.0', '')
        if parts.netloc == 'login.microsoftonline.com':
            form = {k: v[0] for k, v in parse_qs((data or b'').decode()).items()}
            self.calls.append((method, path))
            if form.get('grant_type') == 'refresh_token':
                return self.ok({'access_token': 'at', 'refresh_token': 'rt', 'expires_in': 3600, 'scope': self.scope})
            code = form.get('code', '')
            if code == 'admin-needed':
                return 400, {}, json.dumps({'error': 'invalid_grant', 'error_description': 'AADSTS65001: The user or administrator has not consented to use the application.'}).encode()
            if code == 'bad-secret':
                return 401, {}, json.dumps({'error': 'invalid_client', 'error_description': 'AADSTS7000222: The provided client secret keys for app are expired.'}).encode()
            if code == 'no-mail':
                return self.ok({'access_token': 'at', 'refresh_token': 'rt', 'expires_in': 3600, 'scope': 'openid profile email User.Read', 'id_token': jwt({'preferred_username': ME_M})})
            if not code.startswith(('M.C5', '1.A')):
                return 400, {}, json.dumps({'error': 'invalid_grant', 'error_description': 'AADSTS70000: The provided value for the code was not valid.'}).encode()
            return self.ok({'access_token': 'at', 'refresh_token': 'rt', 'expires_in': 3600, 'scope': self.scope, 'id_token': jwt({'preferred_username': ME_M})})
        if headers.get('Authorization') != 'Bearer at':
            return 401, {}, b'{"error":{"code":"InvalidAuthenticationToken"}}'
        if path == '/me':
            return self.ok({'mail': None, 'userPrincipalName': ME_M})                                           # a personal account: no `mail`, the address is the principal name
        if path.startswith('/me/messages/') and path.endswith('/attachments') and method == 'GET':
            mid = path.split('/')[3]
            return self.ok({'value': [{k: v for k, v in a.items() if k != 'bytes'} for a in self.attached.get(mid, [])]})
        if path.startswith('/me/messages/') and '/attachments/' in path and method == 'GET':
            mid, aid = path.split('/')[3], path.split('/')[5]
            found = next((a for a in self.attached.get(mid, []) if a['id'] == aid), None)
            return self.ok({'contentBytes': base64.b64encode(found['bytes']).decode()}) if found else (404, {}, b'{"error":{"code":"ErrorItemNotFound"}}')
        if path.startswith('/me/messages/') and path.count('/') == 3 and method == 'GET':
            mid = path.split('/')[3]
            m = self.messages.get(mid)
            return self.ok({**m, 'body': {'contentType': 'html', 'content': self.bodies.get(mid, '<p></p>')}}) if m else (404, {}, b'{"error":{"code":"ErrorItemNotFound"}}')
        if path == '/me/calendars':
            return self.ok({'value': [{'id': 'cal-1', 'name': 'Calendar', 'canEdit': True, 'isDefaultCalendar': True, 'owner': {'address': ME_M}}]})
        return super().__call__(method, url, headers, data)


GOOGLE, GRAPH = PreviewGoogle(), PreviewGraph()
if os.environ.get('PREVIEW_MICROSOFT_CHANGES') == '1':                             # Microsoft's changes are held back for customers until proven on a real account; here they can be tried on the fake
    hub_model.PROVING_IN_THIS_PROCESS.update(hub_model.WRITE_CAPABILITIES)
    GRAPH.scope += ' ' + ' '.join('https://graph.microsoft.com/' + g.scope for g in microsoft_hub.GRANTS)


def fake_sign_in(provider):
    """Where the customer is "sent": this fixture's own page, which shows what was asked for and offers each way a sign-in can end."""
    def address(redirect, state, challenge, hint=None, add=(), kind=None):
        real = (google_hub.authorize_url('client-1', redirect, state, challenge, hint=hint, add=add) if provider == 'google'
                else microsoft_hub.authorize_url('cid', redirect, state, challenge, hint=hint, add=add, kind=kind))
        return f'{ORIGIN}/fake/sign-in?' + urlencode({'provider': provider, 'real': real})
    return address


PROVIDERS = {
    'google': {'label': 'Google', 'register': lambda registry: google_hub.register(registry, GOOGLE), 'kinds': (), 'address': fake_sign_in('google'),
               'grants': tuple(g.name for g in google_hub.GRANTS), 'grant_scopes': {g.name: g.scope for g in google_hub.GRANTS},
               'exchange': google_hub.exchanger('client-1', 'secret-1', GOOGLE), 'refresh': google_hub.refresher('client-1', 'secret-1', GOOGLE),
               'needs_any': (google_hub.MAIL_SCOPE, google_hub.CALENDAR_SCOPE)},
    'microsoft': {'label': 'Microsoft', 'register': lambda registry: microsoft_hub.register(registry, GRAPH),
                  'kinds': tuple({'id': name, 'label': label} for name, label, _tenant in microsoft_hub.ACCOUNT_KINDS), 'address': fake_sign_in('microsoft'),
                  'grants': tuple(g.name for g in microsoft_hub.GRANTS), 'grant_scopes': {g.name: g.scope for g in microsoft_hub.GRANTS},
                  'exchange': microsoft_hub.exchanger('cid', 'secret', GRAPH), 'refresh': microsoft_hub.refresher('cid', 'secret', GRAPH),
                  'needs_any': (microsoft_hub.MAIL_SCOPE, microsoft_hub.CALENDAR_SCOPE)}}
wiring.sign_in_providers = lambda: PROVIDERS
_real_switch = wiring.switch_on
ON = {'mail_calendar_dashboard', 'mail_calendar_writes', 'open_access'}
wiring.switch_on = lambda name: name in ON or _real_switch(name)


# -- the fixture's own pages ---------------------------------------------------------------------------------------------------------------------------------
def sign_in_page(query) -> bytes:
    provider, real = query.get('provider', [''])[0], urlsplit(query.get('real', [''])[0])
    asked = {k: v[0] for k, v in parse_qs(real.query).items()}
    back = lambda **values: asked.get('redirect_uri', '') + '?' + urlencode({'state': asked.get('state', ''), **values})
    if provider == 'google':
        ways = [('continue', f'Continue as {ME_G}', back(code='good-code')), ('decline', 'Cancel', back(error='access_denied')), ('bad-code', 'A code Google no longer accepts', back(code='used-code'))]
    else:
        ways = [('continue', f'Continue as {ME_M} (personal)', back(code='M.C5_BAY.2.U.' + 'a' * 40)), ('work', 'Continue with a work account (a long code)', back(code='1.A' + 'B' * 2400, session_state=str(uuid.uuid4()))),
                ('decline', 'Cancel', back(error='access_denied', error_description='AADSTS65004: User declined to consent to access the app.')),
                ('admin', 'An organization where only an administrator may allow apps', back(error='consent_required', error_description='AADSTS65001: The user or administrator has not consented.')),
                ('admin-late', 'The same, found out when the code is traded', back(code='admin-needed')), ('bad-secret', "Lumina's own sign-in app is refused (expired secret)", back(code='bad-secret')),
                ('no-mail', 'Signed in, but mail and calendars both unticked', back(code='no-mail')), ('expired', 'A code Microsoft no longer accepts', back(code='old'))]
    rows = ''.join(f'<p><a id="{name}" href="{href}">{words}</a></p>' for name, words, href in ways)
    return (f'<!doctype html><meta charset="utf-8"><title>Stand-in {provider} sign-in</title><body style="font:15px system-ui;max-width:640px;margin:40px auto">'
            f'<h1>Stand-in sign-in: {provider}</h1><p>This page stands in for the real one. It was reached at <code id="at">{real.netloc}{real.path}</code></p>'
            f'<p>Asked for: <code id="scope">{asked.get("scope", "")}</code></p><p>Account hint: <code id="hint">{asked.get("login_hint", "")}</code></p>{rows}</body>').encode()


django_app = get_wsgi_application()


def application(environ, start_response):
    path = environ.get('PATH_INFO', '')
    if path == '/fake/sign-in':
        body = sign_in_page(parse_qs(environ.get('QUERY_STRING', '')))
        start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8'), ('Content-Length', str(len(body)))])
        return [body]
    if path.startswith('/fake/picture/'):
        name = path.rsplit('/', 1)[1].removesuffix('.png')
        SEEN.append((name, environ.get('QUERY_STRING', ''), environ.get('HTTP_REFERER', '')))
        body = PICTURES.get(name, PICTURES['pixel'])
        start_response('200 OK', [('Content-Type', 'image/png'), ('Content-Length', str(len(body))), ('Cache-Control', 'no-store')])
        return [body]
    if path == '/fake/state':                                                    # what the checks read: what reached the mail services, and which remote pictures were asked for
        body = json.dumps({'pictures': SEEN, 'sent': GOOGLE.outbox, 'modified': GOOGLE.modified, 'microsoft_sent': GRAPH.sent,
                           'google_labels': {m['id']: m['labelIds'] for m in GOOGLE.messages.values()},
                           'microsoft': {m['id']: {'folder': m['parentFolderId'], 'read': m['isRead'], 'flag': (m.get('flag') or {}).get('flagStatus')} for m in GRAPH.messages.values()}}).encode()
        start_response('200 OK', [('Content-Type', 'application/json'), ('Content-Length', str(len(body)))])
        return [body]
    if path == '/fake/expire':                                                   # the provider ends the access of every connected account of that kind
        which = parse_qs(environ.get('QUERY_STRING', '')).get('provider', [''])[0]
        from agentai_platform.store import Store
        connectors = wiring.connector_service()
        with wiring.store().connect() as con:
            ids = [r['id'] for r in con.execute("SELECT id FROM connector_connections WHERE account_id=? AND service=? AND state='connected'", (ACCOUNT, which))]
        for cid in ids:
            connectors.needs_customer(ACCOUNT, cid)
        body = json.dumps({'expired': len(ids)}).encode()
        start_response('200 OK', [('Content-Type', 'application/json'), ('Content-Length', str(len(body)))])
        return [body]
    if path == '/fake/arrive':                                                   # a new message arrives at Gmail
        mid = GOOGLE.add(SENDERS[8], 'Just arrived: can you call me?', text='Call me when you see this.\n\nIvo', ago=0, labels=('INBOX', 'UNREAD'))
        body = json.dumps({'id': mid}).encode()
        start_response('200 OK', [('Content-Type', 'application/json'), ('Content-Length', str(len(body)))])
        return [body]
    environ['wsgi.url_scheme'] = 'https'
    return django_app(environ, start_response)


from django.core.servers.basehttp import ThreadedWSGIServer, WSGIRequestHandler   # noqa: E402  (HTTP/1.1 with kept-alive connections, one thread a connection)


class Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


class Server(ThreadedWSGIServer):
    request_queue_size = 128

    def handle_error(self, request, client_address):                             # a browser closing a connection early is not worth a traceback
        pass


def background():
    """What separate services do on the server: the sync keeps the copy current, and the request worker's action pass sends the changes that waited (Undo send)."""
    sync, runner = wiring.hub_services()[2], wiring.action_runner()
    while True:
        try:
            sync.reconcile(ACCOUNT)
            sync.tick(limit=50)
            runner.tick()
        except Exception as error:                                               # the fixture keeps running; the checks fail on what is missing
            print('background:', type(error).__name__, error, flush=True)
        time.sleep(0.7)


def main():
    cert, key = Path(STATE) / 'cert.pem', Path(STATE) / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-keyout', str(key), '-out', str(cert), '-days', '2', '-nodes', '-subj', '/CN=127.0.0.1',
                    '-addext', 'subjectAltName=IP:127.0.0.1'], check=True, capture_output=True)
    server = Server(('127.0.0.1', PORT), Quiet)
    server.set_app(application)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=background, daemon=True).start()
    print(f'Mail preview: {ORIGIN}/app/inbox   sign in: {EMAIL} / {PASSWORD}   state: {STATE} (disposable)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutil.rmtree(STATE, ignore_errors=True)


if __name__ == '__main__':
    main()
