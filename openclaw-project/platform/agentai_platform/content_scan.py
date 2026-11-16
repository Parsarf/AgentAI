"""The content scan every upload passes before it can be served, read or parsed (roadmap #30). A file is `quarantined` until this says it is safe to keep.

What it is: a structural scan, in this process, with no outside service. It does not look for known malware by signature (an engine for that can be plugged in:
`engine`, for example a local scanning daemon; nothing is sent off the host). It refuses what makes a document dangerous to open or to parse:

* Office files (Word, Excel, PowerPoint in the modern zip format): macros, embedded programs and ActiveX controls, a template or a linked object fetched from somewhere
  else when the file is opened, macro-enabled variants, and anything that is not a well-formed package of the kind its name says. The old binary formats are never
  accepted (files.py refuses them by name);
* PDFs: scripts, actions that start a program, files embedded inside, forms that run code, and encryption (an encrypted file cannot be inspected);
* archives of any kind, and packages built to exhaust memory (too many parts, or parts that expand enormously);
* pictures whose stated size would exhaust memory when decoded.

It never executes, renders or converts anything: it reads bytes. A refusal is one fixed sentence; nothing from inside the file is put in it.
"""
from __future__ import annotations
import io
import re
import struct
import zipfile
import zlib

MAX_PARTS = 5000
MAX_EXPANDED = 300 * 1024 * 1024
MAX_RATIO = 250
MAX_PIXELS = 120_000_000
OFFICE_MAIN = {'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml',
               'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml',
               'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml'}
# A relationship that makes the application fetch or run something from outside the file when it is opened. A plain link in the text (hyperlink) is not one of these.
REMOTE_RELATIONS = ('attachedTemplate', 'oleObject', 'frame', 'externalLink', 'externalLinkPath', 'subDocument', 'control', 'package')
PDF_REFUSED = {b'/JavaScript': 'a script', b'/JS': 'a script', b'/Launch': 'an action that starts a program', b'/EmbeddedFile': 'a file embedded inside it',
               b'/RichMedia': 'embedded media that runs', b'/XFA': 'a form that runs code', b'/Encrypt': 'encryption'}


class Refused(Exception):
    """The file is not kept. The message is a fixed sentence for the customer."""


def office_kind(data: bytes) -> str | None:
    """Which modern Office format a zip is ('docx', 'xlsx', 'pptx'), by what its own content list says its main part is; None when it is some other zip."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            types = package.read('[Content_Types].xml')[:2_000_000].decode('utf-8', 'replace')
    except (zipfile.BadZipFile, KeyError, RuntimeError, OSError, ValueError):
        return None
    return next((kind for kind, main in OFFICE_MAIN.items() if main in types), None)


def _office(kind: str, data: bytes) -> None:
    try:
        package = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError):
        raise Refused('The file is damaged and cannot be read.') from None
    with package:
        parts = package.infolist()
        if len(parts) > MAX_PARTS:
            raise Refused('The file has too many parts to be a normal document.')
        expanded = sum(p.file_size for p in parts)
        if expanded > MAX_EXPANDED or (len(data) and expanded / len(data) > MAX_RATIO):
            raise Refused('The file expands to far more than a document should.')
        if any(p.flag_bits & 0x1 for p in parts):
            raise Refused('The file is password-protected, so it cannot be checked.')
        names = [p.filename for p in parts]
        lowered = [n.lower() for n in names]
        if any(n.endswith('vbaproject.bin') or '/activex/' in n or n.endswith('.exe') or n.endswith('.dll') or n.endswith('.scr') or n.endswith('.js') or n.endswith('.vbs') for n in lowered):
            raise Refused('The file contains macros or a program, which are not accepted.')
        if any('/embeddings/' in n and not n.endswith(('.docx', '.xlsx', '.pptx')) for n in lowered):
            raise Refused('The file has another program\'s object embedded in it, which is not accepted.')
        try:
            types = package.read('[Content_Types].xml')[:2_000_000].decode('utf-8', 'replace')
        except (KeyError, RuntimeError, zipfile.BadZipFile):
            raise Refused('The file is not a well-formed document.') from None
        if OFFICE_MAIN[kind] not in types:
            raise Refused('The file is not the kind of document its name says.')
        if 'macroEnabled' in types or 'vnd.ms-office.vbaProject' in types:
            raise Refused('The file contains macros, which are not accepted.')
        for name in names:
            if not name.lower().endswith('.rels'):
                continue
            try:
                rels = package.read(name)[:2_000_000].decode('utf-8', 'replace')
            except (RuntimeError, zipfile.BadZipFile, zlib.error):
                raise Refused('The file is damaged and cannot be read.') from None
            for relation in re.findall(r'<Relationship\b[^>]*>', rels):
                if 'TargetMode="External"' in relation.replace("'", '"') and any(('/' + word + '"') in relation.replace("'", '"') for word in REMOTE_RELATIONS):
                    raise Refused('The file loads something from elsewhere when it is opened, which is not accepted.')


def _pdf_names(chunk: bytes) -> bytes:
    """PDF names with their #xx escapes undone, so `/J#61vaScript` is seen for what it is."""
    return re.sub(rb'#([0-9A-Fa-f]{2})', lambda m: bytes([int(m.group(1), 16)]), chunk)


def _pdf(data: bytes) -> None:
    seen = [_pdf_names(data)]
    budget = 60 * 1024 * 1024
    for match in re.finditer(rb'stream\r?\n', data):          # compressed object streams can hide a name: look inside the ones that inflate
        end = data.find(b'endstream', match.end())
        if end == -1 or budget <= 0:
            break
        try:
            inflated = zlib.decompressobj().decompress(data[match.end():end], 4 * 1024 * 1024)
        except zlib.error:
            continue
        budget -= len(inflated)
        seen.append(_pdf_names(inflated))
    for chunk in seen:
        for token, what in PDF_REFUSED.items():
            if re.search(re.escape(token) + rb'(?![A-Za-z0-9])', chunk):
                raise Refused(f'The PDF contains {what}, which is not accepted.')


def _picture(kind: str, data: bytes) -> None:
    width = height = 0
    try:
        if kind == 'png' and data[12:16] == b'IHDR':
            width, height = struct.unpack('>II', data[16:24])
        elif kind == 'gif':
            width, height = struct.unpack('<HH', data[6:10])
        elif kind == 'jpeg':
            at = 2
            while at + 9 < len(data) and at < 4_000_000:
                if data[at] != 0xFF:
                    at += 1
                    continue
                marker, size = data[at + 1], struct.unpack('>H', data[at + 2:at + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    height, width = struct.unpack('>HH', data[at + 5:at + 9])
                    break
                at += 2 + size
        elif kind == 'webp' and data[12:16] == b'VP8X':
            width, height = 1 + int.from_bytes(data[24:27], 'little'), 1 + int.from_bytes(data[27:30], 'little')
    except struct.error:
        raise Refused('The picture is damaged and cannot be read.') from None
    if width * height > MAX_PIXELS:
        raise Refused('The picture is too large to be handled safely.')


def scan(kind: str, data: bytes, *, engine=None) -> None:
    """Raise Refused, or return when the content may be kept. `kind` is what files.sniff found the content to be. `engine(data) -> a truthy name when it found something`
    is an optional scanner on this host; a scanner that cannot answer refuses the file (fail closed)."""
    if kind in OFFICE_MAIN:
        _office(kind, data)
    elif kind == 'pdf':
        _pdf(data)
    elif kind in ('png', 'jpeg', 'gif', 'webp'):
        _picture(kind, data)
    elif kind not in ('text', 'json'):
        raise Refused('This kind of file is not accepted.')
    if engine is not None:
        try:
            found = engine(data)
        except Exception:
            raise Refused('The file could not be checked right now. Please try again.') from None
        if found:
            raise Refused('The file was refused by the security check.')
