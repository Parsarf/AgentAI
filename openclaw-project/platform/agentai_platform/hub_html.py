"""Making a mail message safe to show, and good to read (roadmap #D3). Mail is the most hostile content Lumina displays, so a message is rebuilt from an allow-list,
never cleaned by removal.

What comes out of `sanitize`:
* only the tags and attributes listed here; everything else is dropped, and the content of script and the other containers below is dropped with them;
* **the sender's formatting is kept**: `style` attributes and `<style>` sheets are rebuilt declaration by declaration from an allow-list of properties (colours, type,
  spacing, tables, layout). Nothing in them can load anything: an address inside CSS is treated exactly like a picture's;
* no event handler, no form, no frame, no script: nothing that runs or posts;
* links keep an http, https, mailto or tel address only, and always open in a new tab without a referrer;
* **remote pictures are not loaded** unless the customer asked for them for this message or this sender: a remote picture tells the sender that, when and from where the
  message was opened. A blocked picture is counted so the page can say "3 pictures not shown". Pictures carried inside the message (`cid:`) are shown from Lumina's own
  address when the caller says where each is (`inline`); small `data:` pictures are kept (they load nothing);
* earlier messages quoted under a reply are folded behind "Show quoted text" (no script: the browser's own disclosure element).

Two ways a message is shown, decided here (`designed`):
* a message that sets no background anywhere is **plain**: it is shown in Lumina's own theme (its font, its text colour, no surface of its own). The colours its
  sender gave to text are kept where they can be read on the theme and moved just far enough where they cannot (black text on a dark theme would be invisible);
* a message that sets a background is **designed** (a newsletter, a receipt): it was made for a light page, so it is shown exactly as sent, on a light page of its own.

`document` wraps the result in the page a frame shows; `frame_policy` is that page's own content policy. The page a message is shown in comes from Lumina's server with
that policy as a header: a page written into the frame by the app (srcdoc) inherits the APP's policy instead, which allows neither inline styles nor remote pictures, so
every message was shown unstyled (found in production, 2026-11-21). The frame can run nothing either way; this module is the first of two walls, not the only one.
"""
from __future__ import annotations
import colorsys
import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

ALLOWED = {'a', 'abbr', 'address', 'article', 'aside', 'b', 'bdi', 'bdo', 'big', 'blockquote', 'br', 'caption', 'center', 'cite', 'code', 'col', 'colgroup', 'dd', 'del',
           'details', 'dfn', 'div', 'dl', 'dt', 'em', 'figcaption', 'figure', 'font', 'footer', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hr', 'i', 'img', 'ins', 'kbd',
           'li', 'main', 'mark', 'nav', 'ol', 'p', 'pre', 'q', 's', 'samp', 'section', 'small', 'span', 'strike', 'strong', 'sub', 'summary', 'sup', 'table', 'tbody', 'td',
           'tfoot', 'th', 'thead', 'time', 'tr', 'tt', 'u', 'ul', 'var', 'wbr'}
VOID = {'br', 'hr', 'img', 'col', 'wbr'}
DROP_WITH_CONTENT = {'script', 'title', 'iframe', 'frame', 'frameset', 'object', 'embed', 'applet', 'form', 'svg', 'math', 'noscript', 'template', 'audio',
                     'video', 'canvas', 'select', 'textarea', 'button', 'link', 'meta', 'base', 'input', 'xml'}
NO_END = {'link', 'meta', 'base', 'input', 'embed', 'frame'}                       # dropped tags that have no content and no end tag
GLOBAL = {'style', 'class', 'id', 'dir', 'lang', 'title', 'align', 'valign', 'width', 'height', 'bgcolor', 'background', 'role', 'aria-label', 'aria-hidden'}
ATTRIBUTES = {'a': {'href'}, 'img': {'src', 'alt', 'border', 'hspace', 'vspace'}, 'td': {'colspan', 'rowspan', 'nowrap'}, 'th': {'colspan', 'rowspan', 'nowrap', 'scope'},
              'table': {'cellpadding', 'cellspacing', 'border', 'summary'}, 'font': {'size', 'color', 'face'}, 'ol': {'start', 'type'}, 'ul': {'type'}, 'li': {'value'},
              'col': {'span'}, 'colgroup': {'span'}, 'hr': {'size', 'noshade', 'color'}, 'blockquote': {'type'}, 'details': {'open'}}
NUMERIC = {'colspan', 'rowspan', 'cellpadding', 'cellspacing', 'border', 'start', 'span', 'hspace', 'vspace', 'value'}
LENGTH = re.compile(r'\d{1,4}(?:\.\d{1,2})?(?:%|px)?')
MAX_DEPTH = 80
MAX_SHEET = 300_000
MAX_DATA_PICTURE = 400_000
OWN = 'lumina-'                                                  # the prefix of this page's own class names: a message may not use it

# -- colours ----------------------------------------------------------------------------------------------------------------------------------------------
NAMED = {'black': '000000', 'white': 'ffffff', 'red': 'ff0000', 'green': '008000', 'blue': '0000ff', 'yellow': 'ffff00', 'orange': 'ffa500', 'purple': '800080',
         'gray': '808080', 'grey': '808080', 'silver': 'c0c0c0', 'maroon': '800000', 'navy': '000080', 'teal': '008080', 'olive': '808000', 'lime': '00ff00',
         'aqua': '00ffff', 'cyan': '00ffff', 'fuchsia': 'ff00ff', 'magenta': 'ff00ff', 'pink': 'ffc0cb', 'brown': 'a52a2a', 'gold': 'ffd700', 'indigo': '4b0082',
         'violet': 'ee82ee', 'crimson': 'dc143c', 'darkblue': '00008b', 'darkgreen': '006400', 'darkred': '8b0000', 'darkgray': 'a9a9a9', 'darkgrey': 'a9a9a9',
         'dimgray': '696969', 'dimgrey': '696969', 'lightgray': 'd3d3d3', 'lightgrey': 'd3d3d3', 'gainsboro': 'dcdcdc', 'whitesmoke': 'f5f5f5', 'royalblue': '4169e1',
         'steelblue': '4682b4', 'dodgerblue': '1e90ff', 'firebrick': 'b22222', 'tomato': 'ff6347', 'slategray': '708090', 'slategrey': '708090', 'midnightblue': '191970'}
KEYWORD_COLOURS = {'inherit', 'currentcolor', 'transparent', 'initial', 'unset', 'windowtext', 'canvastext', 'linktext', 'graytext', 'buttontext'}
DARK_PAGE, LIGHT_PAGE = (14, 15, 19), (255, 255, 255)            # the surfaces a plain message sits on (close enough to any theme of either kind)
COLOUR_VALUE = re.compile(r'#[0-9a-f]{3,8}|rgba?\([0-9.,%/\s]{1,40}\)|hsla?\([0-9a-z.,%/\s]{1,40}\)|[a-z]{3,24}')


def parse_colour(value):
    """-> (r, g, b, solid) for a colour this module understands, else None."""
    text = str(value or '').strip().lower()
    if text in NAMED:
        text = '#' + NAMED[text]
    if text.startswith('#'):
        digits = text[1:]
        if len(digits) in (3, 4):
            digits = ''.join(c * 2 for c in digits)
        if len(digits) not in (6, 8) or not re.fullmatch(r'[0-9a-f]+', digits):
            return None
        return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16), int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0)
    found = re.fullmatch(r'rgba?\(([^)]*)\)', text)
    if found:
        parts = [p for p in re.split(r'[\s,/]+', found.group(1).strip()) if p]
        if len(parts) not in (3, 4):
            return None
        try:
            channel = lambda p: max(0, min(255, round(float(p[:-1]) * 2.55 if p.endswith('%') else float(p))))
            solid = 1.0 if len(parts) == 3 else max(0.0, min(1.0, float(parts[3][:-1]) / 100 if parts[3].endswith('%') else float(parts[3])))
            return (channel(parts[0]), channel(parts[1]), channel(parts[2]), solid)
        except ValueError:
            return None
    return None


def _luminance(rgb) -> float:
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2])


def contrast(a, b) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _css(rgb, solid=1.0) -> str:
    return '#%02x%02x%02x' % tuple(rgb[:3]) if solid >= 0.999 else f'rgb({rgb[0]} {rgb[1]} {rgb[2]} / {round(solid, 2)})'


def _moved(rgb, page):
    """The same hue, lighter or darker by just enough to be read on `page`."""
    h, l, s = colorsys.rgb_to_hls(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)
    lighter = _luminance(page) < 0.5
    near, far = l, 1.0 if lighter else 0.0
    for _ in range(12):
        mid = (near + far) / 2
        tried = tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, mid, s))
        if contrast(tried, page) >= 5:
            far = mid
        else:
            near = mid
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, far, s))


def readable(value) -> str | None:
    """A text colour for a PLAIN message, which is shown on the theme's own surface: the sender's colour where it can be read there, moved just far enough where it
    cannot. Black or dark grey text ("ordinary text") becomes the theme's text colour. -> a CSS value, or None to drop the declaration (the theme's colour is used)."""
    text = str(value or '').strip().lower()
    if text in KEYWORD_COLOURS:
        return text
    found = parse_colour(text)
    if found is None:
        return None
    rgb, solid = found[:3], found[3]
    plain = _css(rgb, solid)
    grey = max(rgb) - min(rgb) < 28

    def on(page, ink):
        if contrast(rgb, page) >= 4.5:
            return plain
        return ink if grey else _css(_moved(rgb, page), solid)
    light, dark = on(LIGHT_PAGE, 'var(--lm-fg, #1b1c20)'), on(DARK_PAGE, 'var(--lm-fg, #f2f2f5)')
    return plain if light == dark == plain else f'light-dark({light}, {dark})'


# -- CSS --------------------------------------------------------------------------------------------------------------------------------------------------
PROPERTY = re.compile(
    r'color|background(-(color|image|repeat|position|size|clip|origin))?|border(-(top|right|bottom|left))?(-(color|style|width))?|border-(collapse|spacing)|'
    r'border-((top|bottom)-(left|right)-)?radius|margin(-(top|right|bottom|left))?|padding(-(top|right|bottom|left))?|font(-(family|size|style|weight|variant|stretch))?|'
    r'line-height|letter-spacing|word-spacing|word-break|word-wrap|overflow-wrap|white-space|text-(align|decoration|decoration-line|decoration-color|decoration-style|indent|'
    r'transform|overflow|shadow|underline-offset)|vertical-align|(min-|max-)?(width|height)|display|float|clear|overflow(-x|-y)?|list-style(-type|-position)?|table-layout|'
    r'caption-side|empty-cells|direction|unicode-bidi|opacity|visibility|box-sizing|box-shadow|outline(-(color|style|width|offset))?|position|top|right|bottom|left|z-index|'
    r'flex(-(direction|wrap|grow|shrink|basis|flow))?|align-(items|self|content)|justify-(content|items|self)|gap|row-gap|column-gap|order|object-fit|object-position|'
    r'hyphens|tab-size|content|mso-line-height-rule')
BACKGROUNDS = {'background', 'background-color', 'background-image'}
NOT_A_BACKGROUND = {'', 'none', 'transparent', 'inherit', 'initial', 'unset', 'none transparent', 'transparent none'}
FORBIDDEN = re.compile(r'[\\<>{}]|/\*|expression|javascript:|vbscript:|behavio[u]?r|-moz-binding|@|image-set|element\(|\bpaint\(|!ie', re.I)
ADDRESS = re.compile(r'url\(\s*(?:"([^"]*)"|\'([^\']*)\'|([^)\'"]*))\s*\)', re.I)
SELECTOR = re.compile(r'[A-Za-z0-9_\-.#*>+~:,\s\[\]="\'()^$|]{1,600}')


class _Context:
    """What one pass over a message notes on the way."""
    def __init__(self, images, plain):
        self.images, self.plain, self.blocked, self.designed = images, plain, 0, False


def _link(value, schemes=('http', 'https', 'mailto', 'tel')) -> str | None:
    value = ''.join(ch for ch in str(value or '') if ch > ' ' and ch != '\x7f')
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme in ('http', 'https') and parts.scheme in schemes and parts.netloc:
        return value[:2000]
    if parts.scheme in ('mailto', 'tel') and parts.scheme in schemes and parts.path:
        return value[:500]
    return None


def _declarations(text):
    """`a: b; c: d` split at the semicolons that are not inside a string or brackets."""
    part, depth, quote = [], 0, ''
    for ch in str(text or '')[:20_000]:
        if quote:
            if ch == quote:
                quote = ''
        elif ch in '"\'':
            quote = ch
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(0, depth - 1)
        elif ch == ';' and not depth:
            yield ''.join(part)
            part = []
            continue
        part.append(ch)
    if part:
        yield ''.join(part)


def clean_style(text, ctx) -> str:
    """A `style` value (or the inside of a rule) rebuilt: allowed properties only, no value that could run or load, addresses inside it treated as pictures."""
    kept = []
    for raw in _declarations(text):
        name, colon, value = raw.partition(':')
        name, value = name.strip().lower(), ' '.join(value.split())
        important = value.lower().endswith('!important')
        if important:
            value = value[:-10].strip()
        if not colon or not value or len(value) > 1500 or not PROPERTY.fullmatch(name):
            continue
        low = value.lower()
        if name == 'position' and low in ('fixed', 'sticky'):
            continue
        if name == 'content' and not re.fullmatch(r'"[^"<>\\\\]{0,80}"|\'[^\'<>\\\\]{0,80}\'|none|normal', value):
            continue
        found_addresses = []

        def address(found):
            target = _link(next((g for g in found.groups() if g is not None), ''), ('http', 'https'))
            if target is None:
                return 'none'
            if not ctx.images:
                ctx.blocked += 1
                return 'none'
            found_addresses.append('url("' + target.replace('"', '%22').replace('\\', '%5C') + '")')
            return f'\x00{len(found_addresses) - 1}\x00'
        value = ADDRESS.sub(address, value)                       # addresses are taken out first: what is checked next is everything that is not an address
        if FORBIDDEN.search(value) or 'url(' in value.lower():
            continue
        value = re.sub(r'\x00(\d+)\x00', lambda m: found_addresses[int(m.group(1))], value)
        if name in BACKGROUNDS and value.lower() not in NOT_A_BACKGROUND:
            ctx.designed = True
        if name == 'color' and ctx.plain:
            value = readable(value)
            if value is None:
                continue
        kept.append(f'{name}:{value}{" !important" if important else ""}')
    return ';'.join(kept)[:6000]


def clean_sheet(text, ctx) -> str:
    """A `<style>` sheet rebuilt: ordinary rules and `@media` blocks, each rule's declarations rebuilt like a `style` value. Everything else that starts with `@`
    (imports, fonts, animations) is dropped with its block."""
    text = re.sub(r'/\*.*?\*/', ' ', str(text or '')[:MAX_SHEET], flags=re.S).replace('<!--', ' ').replace('-->', ' ')
    out, at, size = [], 0, len(text)

    def block(start):
        """-> (inside, index after the closing brace) for the block whose opening brace is at `start`."""
        depth, i = 0, start
        while i < size:
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    return text[start + 1:i], i + 1
            i += 1
        return text[start + 1:], size

    while at < size and len(out) < 2000:
        brace, stop = text.find('{', at), text.find(';', at)
        if brace < 0:
            break
        head = text[at:brace].strip()
        if head.startswith('@') and 0 <= stop < brace:          # a statement such as @import or @charset: dropped
            at = stop + 1
            continue
        inside, at = block(brace)
        if head.lower().startswith('@media'):
            query = ' '.join(head[6:].split())
            if re.fullmatch(r'[A-Za-z0-9\s(),:.\-/]{0,200}', query):
                inner = clean_sheet(inside, ctx)
                if inner:
                    out.append(f'@media {query}{{{inner}}}')
            continue
        if head.startswith('@') or not head or not SELECTOR.fullmatch(head) or OWN in head.lower() or re.search(r'url\(|expression', head, re.I):
            continue
        rules = clean_style(inside, ctx)
        if rules:
            out.append(f'{" ".join(head.split())}{{{rules}}}')
    return ''.join(out)


# -- markup -----------------------------------------------------------------------------------------------------------------------------------------------
QUOTE_CLASSES = {'gmail_quote', 'gmail_extra', 'yahoo_quoted', 'protonmail_quote', 'zmail_extra'}
REST_IDS = {'divrplyfwdmsg', 'appendonsend', 'mail-editor-reference-message-container'}
REST_CLASSES = {'moz-cite-prefix', 'outlookmessageheader'}
FORWARD = re.compile(r'forwarded message|begin forwarded|weitergeleitete nachricht|message transf[ée]r[ée]', re.I)
FOLD_OPEN = ('<details class="lumina-quote"><summary><span class="lumina-show">Show quoted text</span><span class="lumina-hide">Hide quoted text</span></summary>'
             '<div class="lumina-quoted">')
FOLD_CLOSE = '</div></details>'


def _quote(tag, attrs) -> str | None:
    """Is this element where the earlier messages quoted under a reply begin? 'element': they are inside it. 'rest': it is their heading, and they follow it."""
    classes = set(str(attrs.get('class') or '').lower().split())
    if tag == 'blockquote' and (str(attrs.get('type') or '').lower() == 'cite' or classes & QUOTE_CLASSES):
        return 'element'
    if tag != 'div':
        return None
    if classes & QUOTE_CLASSES:
        return 'element'
    if str(attrs.get('id') or '').lower() in REST_IDS or classes & REST_CLASSES:
        return 'rest'
    style = str(attrs.get('style') or '').lower().replace(' ', '')
    if 'border-top:solid' in style and 'padding:3.0pt0' in style and 'border:none' in style:      # the rule one desktop mail program draws above "From: ... Sent: ..."
        return 'rest'
    return None


class _Rebuilder(HTMLParser):
    def __init__(self, ctx, inline):
        super().__init__(convert_charrefs=True)
        self.ctx, self.inline = ctx, inline or {}
        self.out, self.open, self.dropping = [], [], []
        self.began = []                                            # for each open element: (where its start tag is in `out`, the text written before it)
        self.sheet = None                                          # the text of a <style> being read
        self.written = 0                                           # characters of text put out so far (a quote is folded only under something)
        self.fold, self.folded, self.fold_text = None, False, []

    # -- attributes ------------------------------------------------------------------------------------------------------------------------------------
    def _attributes(self, tag, attrs):
        """-> (the attributes to write, as text; the styles to add in front of the element's own)."""
        given, kept, style = {}, [], []
        for name, value in attrs:
            given.setdefault(name, '' if value is None else str(value))
        allowed = GLOBAL | ATTRIBUTES.get(tag, set())
        for name, value in given.items():
            if name not in allowed:
                continue
            if name == 'style':
                continue                                           # written last, after what the old-style attributes add
            if name == 'href':
                value = _link(value)
                if value is None:
                    continue
            elif name == 'src':
                value = self._picture(value)
                if value is None:
                    continue
            elif name == 'background':
                address = _link(value, ('http', 'https'))
                if address is None:
                    continue
                self.ctx.designed = True
                if not self.ctx.images:
                    self.ctx.blocked += 1
                    continue
                style.append('background-image:url("' + address.replace('"', '%22') + '")')
                continue
            elif name == 'bgcolor':
                colour = value.strip()
                if parse_colour(colour) is None and not re.fullmatch(r'[0-9a-fA-F]{6}', colour):
                    continue
                self.ctx.designed = True
                style.append('background-color:' + (colour if parse_colour(colour) else '#' + colour))
                continue
            elif name == 'color':
                colour = value.strip() if parse_colour(value.strip()) else ('#' + value.strip() if re.fullmatch(r'[0-9a-fA-F]{6}', value.strip()) else None)
                if colour is None:
                    continue
                colour = readable(colour) if self.ctx.plain else colour
                if colour:
                    style.append(('border-color:' if tag == 'hr' else 'color:') + colour)
                continue
            elif name == 'face':
                if not re.fullmatch(r'[A-Za-z0-9 ,\-\'"]{1,120}', value):
                    continue
                style.append('font-family:' + value.replace('"', "'"))
                continue
            elif name in ('width', 'height'):
                value = value.strip().lower()
                if not LENGTH.fullmatch(value):
                    continue
                value = value[:-2] if value.endswith('px') else value
            elif name in NUMERIC or (name == 'size' and tag == 'hr'):
                value = value.strip()
                if not value.isdigit() or len(value) > 4:
                    continue
            elif name == 'size':                                   # <font size>: 1 to 7, or a step up or down
                if not re.fullmatch(r'[+-]?[1-7]', value.strip()):
                    continue
                value = value.strip()
            elif name in ('class', 'id'):
                words = [w for w in re.findall(r'[A-Za-z0-9_\-]{1,80}', value) if not w.lower().startswith(OWN)][:20]
                if not words:
                    continue
                value = ' '.join(words) if name == 'class' else words[0]
            elif name in ('align', 'valign', 'dir', 'type', 'scope', 'role', 'aria-hidden'):
                value = value.strip().lower()
                if not re.fullmatch(r'[a-z0-9]{1,20}', value):
                    continue
            elif name in ('nowrap', 'noshade', 'open'):
                value = ''
            else:
                value = value[:300]
            kept.append(f' {name}="{escape(value, quote=True)}"' if value != '' or name in ('alt',) else f' {name}')
        own = clean_style(given.get('style', ''), self.ctx) if 'style' in given else ''
        joined = ';'.join([*style, own] if own else style)
        if joined:
            kept.append(f' style="{escape(joined, quote=True)}"')
        return ''.join(kept), given

    def _picture(self, value) -> str | None:
        text = ''.join(ch for ch in str(value or '') if ch > ' ' and ch != '\x7f')
        low = text.lower()
        if low.startswith('cid:'):
            return self.inline.get(text[4:].strip('<>')) or self.inline.get(text[4:].strip('<>').lower())
        if low.startswith('data:'):
            return text if re.match(r'data:image/(png|jpe?g|gif|webp);base64,[A-Za-z0-9+/=]+$', text) and len(text) <= MAX_DATA_PICTURE else None
        address = _link(text, ('http', 'https'))
        if address is None:
            return None
        if not self.ctx.images:
            self.ctx.blocked += 1
            return None
        return address

    # -- the quoted part ---------------------------------------------------------------------------------------------------------------------------------
    def _end_fold(self):
        fold, self.fold = self.fold, None
        if FORWARD.search(''.join(self.fold_text)[:400]) or sum(len(t) for t in self.fold_text) == 0:
            return                                                 # a forwarded message is what the mail is about, not an old quote: shown
        self.out.insert(fold['at'], FOLD_OPEN)
        self.out.append(FOLD_CLOSE)
        self.folded = True

    # -- the parser --------------------------------------------------------------------------------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag == 'style' and not self.dropping:
            self.sheet = []
            return
        if tag in DROP_WITH_CONTENT:
            if tag not in NO_END:
                self.dropping.append(tag)
            return
        if self.dropping or self.sheet is not None:
            return
        if tag == 'body':                                          # the message's own page colours belong to the message: kept on a block of its own
            written, _given = self._attributes('div', [(n, v) for n, v in attrs if n in ('style', 'bgcolor', 'background', 'dir', 'lang', 'class', 'id')])
            if written:
                self.began.append((len(self.out), self.written))
                self.out.append(f'<div{written}>')
                self.open.append('div')
            return
        if tag not in ALLOWED or len(self.open) >= MAX_DEPTH:
            return
        written, given = self._attributes(tag, attrs)
        if tag == 'img':
            if ' src=' not in written:
                alt = ' '.join(str(given.get('alt') or '').split())[:120]
                if alt and self.ctx.blocked and not self.ctx.images:
                    self.out.append(f'<span class="lumina-alt">{escape(alt, quote=False)}</span>')
                return
        if tag == 'a':
            written += ' target="_blank" rel="noopener noreferrer nofollow"'
        if self.fold is None and not self.folded and self.written > 0 and tag not in VOID:
            kind = _quote(tag, given)
            if kind:
                self.fold, self.fold_text = {'at': len(self.out), 'depth': len(self.open), 'kind': kind, 'written': self.written}, []
        if tag not in VOID:
            self.began.append((len(self.out), self.written))
            self.open.append(tag)
        self.out.append(f'<{tag}{written}>')

    def handle_startendtag(self, tag, attrs):
        if tag in VOID:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == 'style' and self.sheet is not None:
            sheet, self.sheet = clean_sheet(''.join(self.sheet), self.ctx), None
            if sheet and not self.dropping:
                self.out.append(f'<style>{sheet}</style>')
            return
        if self.dropping:
            if tag in self.dropping:
                while self.dropping.pop() != tag:
                    pass
            return
        if tag in ('body', 'html'):                                # whatever is still open is closed at the end
            return
        if tag in self.open:
            while self.open:
                last = self._close_one()
                if last == tag:
                    break

    def _close_one(self) -> str:
        """Close the innermost open element, ending a fold that ends with it. A heading of quoted messages ('rest') is often wrapped in a block of its own with the
        quoted messages after that block: when the block that closes held nothing but the heading, the fold is moved out to begin at that block and carries on."""
        last = self.open.pop()
        at, written_before = self.began.pop()
        fold = self.fold
        if fold and fold['kind'] == 'rest' and len(self.open) < fold['depth']:
            if written_before == fold['written'] and len(self.open) > 0:
                fold['at'], fold['depth'] = at, len(self.open)
            else:
                self._end_fold()
        self.out.append(f'</{last}>')
        if self.fold and self.fold['kind'] == 'element' and len(self.open) <= self.fold['depth']:
            self._end_fold()
        return last

    def handle_data(self, data):
        if self.sheet is not None:
            self.sheet.append(data)
        elif not self.dropping:
            self.out.append(escape(data, quote=False))
            seen = len(data.strip())
            self.written += seen
            if self.fold is not None and seen:
                self.fold_text.append(data)

    def handle_comment(self, data):
        if self.sheet is not None:                                 # sheets are often written inside a comment
            self.sheet.append(data)

    def result(self) -> str:
        while self.open:
            if self.fold and self.fold['kind'] == 'rest' and len(self.open) <= self.fold['depth']:
                self._end_fold()                                   # what is still open when the message ends closes after the fold, not inside it
            self._close_one()
        if self.fold:
            self._end_fold()
        return ''.join(self.out)


def _rebuild(html, images, inline, plain):
    ctx = _Context(images, plain)
    worker = _Rebuilder(ctx, inline)
    worker.feed(str(html or '')[:1_000_000])
    worker.close()
    return worker.result(), ctx, worker.folded


def sanitize(html: str, *, images: bool = False, inline: dict | None = None) -> dict:
    """-> {'html': the rebuilt message, 'blocked_images': how many remote pictures were left out, 'designed': it sets a background (shown as sent, on a light page of
    its own) or not (shown in the theme), 'quoted': earlier messages were folded}. `inline`: {content id: address} for the pictures carried inside the message.
    Never raises: what cannot be parsed is shown as text."""
    try:
        out, ctx, folded = _rebuild(html, images, inline, True)
        if ctx.designed:                                           # as sent: the colours are not touched (read once more, because the first pass moved them)
            out, ctx, folded = _rebuild(html, images, inline, False)
        return {'html': out, 'blocked_images': ctx.blocked, 'designed': bool(ctx.designed), 'quoted': folded}
    except Exception:
        return {'html': escape(str(html or '')[:200_000], quote=False), 'blocked_images': 0, 'designed': False, 'quoted': False}


WEB_ADDRESS = re.compile(r'https?://[^\s<>"\')\]]{3,1000}')
QUOTED_LINE = re.compile(r'\s*>')
WROTE_LINE = re.compile(r'.{0,200}(wrote|schrieb|a écrit|escribió|ha scritto)\s*:\s*$', re.I)


def _text_markup(text) -> str:
    """Plain text as safe markup: escaped, with the web addresses in it as links."""
    out, at = [], 0
    for found in WEB_ADDRESS.finditer(text):
        address = found.group(0).rstrip('.,;:!?')
        target = _link(address, ('http', 'https'))
        if target is None:
            continue
        out.append(escape(text[at:found.start()], quote=False))
        out.append(f'<a href="{escape(target, quote=True)}" target="_blank" rel="noopener noreferrer nofollow">{escape(address, quote=False)}</a>')
        at = found.start() + len(address)
    out.append(escape(text[at:], quote=False))
    return ''.join(out)


def from_text(text: str) -> str:
    """A plain-text message as safe markup: escaped, its line breaks kept, its web addresses as links, and the earlier messages quoted at its end ("> ...") folded."""
    text = str(text or '')[:400_000]
    lines = text.split('\n')
    cut = len(lines)
    while cut > 0 and (not lines[cut - 1].strip() or QUOTED_LINE.match(lines[cut - 1])):
        cut -= 1
    quoted = any(QUOTED_LINE.match(l) for l in lines[cut:])
    if quoted and cut > 0 and WROTE_LINE.match(lines[cut - 1]):
        cut -= 1
        if cut > 0 and not lines[cut - 1].strip():
            cut -= 1
    own = '\n'.join(lines[:cut])
    if not quoted or not own.strip() or FORWARD.search('\n'.join(lines[cut:cut + 4])):
        return '<pre class="lumina-text">' + _text_markup(text) + '</pre>'
    return ('<pre class="lumina-text">' + _text_markup(own.rstrip('\n')) + '</pre>' + FOLD_OPEN + '<pre class="lumina-text">'
            + _text_markup('\n'.join(lines[cut:]).strip('\n')) + '</pre>' + FOLD_CLOSE)


class _Words(HTMLParser):
    BLOCKS = {'p', 'div', 'br', 'tr', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'table', 'hr', 'pre'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head', 'title'):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.out.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head', 'title'):
            self.skip = max(0, self.skip - 1)
        elif tag in ('p', 'div', 'tr', 'table', 'blockquote'):
            self.out.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def to_text(html: str) -> str:
    """The words of a message that came as markup only: what a reply quotes and what the customer's search looks through. Never raises."""
    try:
        worker = _Words()
        worker.feed(str(html or '')[:1_000_000])
        worker.close()
        lines = [' '.join(line.split()) for line in ''.join(worker.out).replace('\xa0', ' ').split('\n')]
    except Exception:
        return ''
    out, blank = [], False
    for line in lines:
        if line or not blank:
            out.append(line)
        blank = not line
    return '\n'.join(out).strip()[:400_000]


# -- the page a frame shows ---------------------------------------------------------------------------------------------------------------------------------
BASE_STYLE = (
    'html{margin:0;padding:0;-webkit-text-size-adjust:100%;text-size-adjust:100%}'
    'body{margin:0;padding:0;display:flow-root;overflow-wrap:anywhere;word-break:normal}'
    'img{max-width:100%;height:auto}table{max-width:100%}pre{white-space:pre-wrap;margin:0}'
    '.lumina-text{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere}'
    '.lumina-alt{display:inline-block;padding:1px 6px;border:1px dashed var(--lm-line,GrayText);border-radius:6px;font-size:12px;opacity:.8}'
    '.lumina-quote{margin:12px 0 0}'
    '.lumina-quote>summary{display:inline-block;list-style:none;cursor:pointer;padding:2px 10px;border:1px solid var(--lm-line,GrayText);border-radius:999px;'
    'font:500 12px/1.6 var(--lm-font,system-ui,sans-serif);color:var(--lm-muted,GrayText);user-select:none}'
    '.lumina-quote>summary::-webkit-details-marker{display:none}'
    '.lumina-quote>summary:focus-visible{outline:2px solid var(--lm-accent,Highlight);outline-offset:2px}'
    '.lumina-quote[open]>summary{margin-bottom:10px}'
    '.lumina-quote .lumina-hide,.lumina-quote[open] .lumina-show{display:none}.lumina-quote[open] .lumina-hide{display:inline}'
    '.lumina-quoted{overflow-wrap:anywhere}')
# Plain: the theme's own type and colours (the app sets the --lm-* values and the colour scheme on this page's root once it has loaded; until then, and if it cannot,
# the browser's own colours for the person's light or dark setting are used).
PLAIN_STYLE = (
    'html{color-scheme:light dark;background:transparent}'
    'body{font:14px/1.6 var(--lm-font,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif);color:var(--lm-fg,CanvasText);background:transparent}'
    'a{color:var(--lm-link,LinkText)}'
    'blockquote{margin:8px 0;padding:0 0 0 12px;border-left:2px solid var(--lm-line,GrayText);color:var(--lm-muted,GrayText)}'
    'hr{border:0;border-top:1px solid var(--lm-line,GrayText)}'
    'h1,h2,h3{line-height:1.3}p{margin:0 0 .8em}p:last-child{margin-bottom:0}'
    'td,th{vertical-align:top}')
# Designed: as sent, on a light page (what its sender made it for), whatever the theme.
DESIGNED_STYLE = (
    'html{color-scheme:light;background:#ffffff}'
    'body{font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;color:#1f2328;background:#ffffff}'
    'a{color:#0b57d0}'
    '.lumina-quote{padding:0 12px 12px}')


def document(inner: str, *, designed: bool) -> str:
    """The whole page a message's frame shows. Its own content policy travels with it as a header (`frame_policy`), and is repeated here for a copy that is ever opened
    without that header."""
    kind = 'designed' if designed else 'plain'
    return ('<!doctype html><html class="lumina-' + kind + '"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="referrer" content="no-referrer"><style>' + BASE_STYLE + (DESIGNED_STYLE if designed else PLAIN_STYLE) + '</style></head>'
            '<body>' + inner + '</body></html>')


def frame_policy(images: bool) -> str:
    """The content policy of a message's page: nothing runs, nothing is posted, nothing is loaded but styles written in the page, pictures (Lumina's own address for the
    ones carried in the message, any address only once the customer asked for remote pictures) and Lumina's own font. It may be shown only inside Lumina."""
    pictures = "img-src 'self' data: https: http:" if images else "img-src 'self' data:"
    return ("default-src 'none'; style-src 'unsafe-inline'; " + pictures + "; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'; "
            "sandbox allow-same-origin allow-popups allow-popups-to-escape-sandbox")
