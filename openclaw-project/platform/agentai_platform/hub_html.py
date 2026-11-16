"""Making a mail message safe to show (roadmap #D3). Mail is the most hostile content Lumina displays, so a message is rebuilt from an allow-list, never cleaned by removal.

What comes out:
* only the tags and attributes listed here; everything else is dropped, and the content of script, style and the other containers below is dropped with them;
* no `style`, no event handler, no form, no frame: nothing that runs, posts or loads;
* links keep an http, https or mailto address only, and always open in a new tab without a referrer;
* **remote pictures are not loaded** unless the customer asked for them for this message or this sender: a remote picture tells the sender that, when and from where the
  message was opened. A blocked picture is counted so the page can say "3 pictures not shown". Pictures carried inside the message (`cid:`) and `data:` addresses are dropped.

The web app shows the result inside a sandboxed frame as well; this module is the first of two walls, not the only one.
"""
from __future__ import annotations
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

ALLOWED = {'a', 'abbr', 'b', 'blockquote', 'br', 'caption', 'center', 'code', 'col', 'colgroup', 'dd', 'div', 'dl', 'dt', 'em', 'font', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
           'hr', 'i', 'img', 'li', 'ol', 'p', 'pre', 's', 'small', 'span', 'strike', 'strong', 'sub', 'sup', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'u', 'ul'}
VOID = {'br', 'hr', 'img', 'col'}
DROP_WITH_CONTENT = {'script', 'style', 'head', 'title', 'iframe', 'frame', 'frameset', 'object', 'embed', 'applet', 'form', 'svg', 'math', 'noscript', 'template', 'audio',
                     'video', 'canvas', 'select', 'textarea', 'button', 'link', 'meta', 'base'}
ATTRIBUTES = {'a': {'href', 'title'}, 'img': {'src', 'alt', 'title', 'width', 'height'}, 'td': {'colspan', 'rowspan', 'align', 'valign'}, 'th': {'colspan', 'rowspan', 'align', 'valign'},
              'table': {'align', 'width', 'cellpadding', 'cellspacing', 'border'}, 'font': {'size'}, 'ol': {'start'}, 'col': {'span', 'width'}, 'div': {'align'}, 'p': {'align'}}
NUMERIC = {'width', 'height', 'colspan', 'rowspan', 'cellpadding', 'cellspacing', 'border', 'size', 'start', 'span'}
MAX_DEPTH = 60


def _link(value) -> str | None:
    value = ''.join(ch for ch in str(value or '') if ch > ' ' and ch != '\x7f')
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme in ('http', 'https') and parts.netloc:
        return value[:2000]
    if parts.scheme == 'mailto' and parts.path:
        return value[:500]
    return None


class _Rebuilder(HTMLParser):
    def __init__(self, images):
        super().__init__(convert_charrefs=True)
        self.images, self.out, self.open, self.dropping, self.blocked = images, [], [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            if tag not in ('link', 'meta', 'base'):         # those three have no content and no end tag
                self.dropping.append(tag)
            return
        if self.dropping:
            return
        if tag not in ALLOWED or len(self.open) >= MAX_DEPTH:
            return
        kept = []
        for name, value in attrs:
            if name not in ATTRIBUTES.get(tag, ()):
                continue
            value = '' if value is None else str(value)
            if name == 'href':
                value = _link(value)
                if value is None:
                    continue
            elif name == 'src':
                address = _link(value)
                if address is None or not address.startswith(('http://', 'https://')):
                    continue                                # carried in the message, or a data address: not shown
                if not self.images:
                    self.blocked += 1
                    continue
                value = address
            elif name in NUMERIC:
                value = value.strip().rstrip('%')
                if not value.isdigit() or len(value) > 4:
                    continue
            else:
                value = value[:300]
            kept.append(f' {name}="{escape(value, quote=True)}"')
        if tag == 'img' and not any(k.startswith(' src=') for k in kept):
            return
        if tag == 'a':
            kept.append(' target="_blank" rel="noopener noreferrer nofollow"')
        self.out.append(f'<{tag}{"".join(kept)}>')
        if tag not in VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in VOID:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.dropping:
            if tag in self.dropping:
                while self.dropping.pop() != tag:
                    pass
            return
        if tag in self.open:
            while self.open:
                last = self.open.pop()
                self.out.append(f'</{last}>')
                if last == tag:
                    break

    def handle_data(self, data):
        if not self.dropping:
            self.out.append(escape(data, quote=False))

    def result(self) -> str:
        while self.open:
            self.out.append(f'</{self.open.pop()}>')
        return ''.join(self.out)


def sanitize(html: str, *, images: bool = False) -> dict:
    """-> {'html': the rebuilt message, 'blocked_images': how many remote pictures were left out}. Never raises: what cannot be parsed is shown as text."""
    worker = _Rebuilder(images)
    try:
        worker.feed(str(html or '')[:1_000_000])
        worker.close()
        return {'html': worker.result(), 'blocked_images': worker.blocked}
    except Exception:
        return {'html': escape(str(html or '')[:200_000], quote=False), 'blocked_images': 0}


def from_text(text: str) -> str:
    """A plain-text message as safe markup: escaped, with its line breaks kept."""
    return '<pre>' + escape(str(text or '')[:400_000], quote=False) + '</pre>'
