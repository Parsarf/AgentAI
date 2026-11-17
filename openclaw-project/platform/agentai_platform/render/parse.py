"""The document parser (roadmap #31 to #34). Runs INSIDE the renderer container (deploy/renderer/Dockerfile), like engine.py: no network, read-only root, no
capabilities, one job, then gone. Standard library plus poppler's command-line tools (pdftotext, pdfinfo, pdfimages, pdftoppm). It never imports the platform.

It turns one file into ONE structure that reading, search, comparison and citation all use (#32):

    {"format": "pdf", "pages": 12, "title": "...",
     "blocks": [{"id": "b7", "kind": "heading|paragraph|list|table|figure|chart|code|header|notes", "page": 3, "bbox": [x0, y0, x1, y1] (fractions of the page),
                 "text": "...", "level": 2, "items": [...], "rows": [[...]], "header_rows": 1, "series": [...], "source": "text|data", ...}],
     "vision": [{"page": 4, "why": "no_text|figure", "image": "page-0004.jpg"}],
     "notes": ["..."]}

Pages that carry no text (a scan, a photo) and pictures that may be charts are not guessed at here: they are listed in "vision" with a picture of the page, and the
host reads them with the vision model (knowledge_parse.py), outside this container, because this container has nowhere to send anything.

Everything in /job/in came from a customer or from the web: it is only ever read as data. Nothing in it is executed.
"""
from __future__ import annotations
import csv
import email
import email.policy
import html
import io
import json
import re
import shutil
import statistics
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

VERSION = 'lumina-parse-1'
MAX_PAGES = 400
MAX_VISION_PAGES = 40
MAX_BLOCKS = 20000
MAX_TEXT = 6000                      # one block's text
MAX_ROWS = 5000
MAX_COLS = 60
MAX_ZIP_BYTES = 250 * 1024 * 1024
STEP_SECONDS = 90
FIGURE_SHARE = 0.12                  # a picture that covers more of the page than this may be a chart: the page is read by the vision model as well
MIN_PAGE_TEXT = 25                   # fewer characters than this on a PDF page: it is a scan (or empty) and goes to the vision model
IMAGE_EXT = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'webp': 'image/webp', 'gif': 'image/gif'}
BULLET = re.compile(r'^\s*(?:[•▪◦·–—\-\*●■]|\(?\d{1,3}[.)]|\(?[a-zA-Z][.)])\s+')
TOOL_PATH = '/usr/bin:/bin'              # the container's tools; the tests point it at the build machine's
NUMBER = re.compile(r'^[\s(]*[-+−]?[$€£¥]?\s?\d[\d,.\s]*%?[)\s]*$')


class Failed(Exception):
    """The file could not be read, with a short reason that is safe to show (never a path or tool output)."""


def ext(name: str) -> str:
    return name.rsplit('.', 1)[-1].lower() if '.' in name else ''


def clip(text, n=MAX_TEXT):
    text = re.sub(r'[ \t ]+', ' ', str(text or '')).strip()
    return text[:n]


def is_number(text) -> bool:
    return bool(text) and bool(NUMBER.match(str(text))) and any(c.isdigit() for c in str(text))


def run(argv, *, what, capture=False, cwd='/tmp'):
    env = {'HOME': '/tmp/home', 'PATH': TOOL_PATH, 'LANG': 'C.UTF-8', 'TMPDIR': '/tmp'}
    try:
        done = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=STEP_SECONDS)
    except subprocess.TimeoutExpired:
        raise Failed(f'{what} took too long')
    except OSError:
        raise Failed(f'{what} is not available')
    if done.returncode != 0:
        raise Failed(f'{what} could not read this file')
    return done.stdout if capture else b''


class Doc:
    """What a parser builds: blocks in reading order, with ids."""

    def __init__(self, fmt):
        self.format, self.blocks, self.vision, self.notes, self.pages, self.title = fmt, [], [], [], None, ''

    def add(self, kind, text='', **extra):
        if len(self.blocks) >= MAX_BLOCKS:
            if 'too many parts' not in self.notes:
                self.notes.append('too many parts: the rest of the document was not read')
            return None
        block = {'id': f'b{len(self.blocks) + 1}', 'kind': kind, 'text': clip(text), 'source': extra.pop('source', 'text')}
        block.update({k: v for k, v in extra.items() if v is not None})
        self.blocks.append(block)
        return block

    def table(self, rows, *, page=None, title=None, header_rows=None, **extra):
        rows = [[clip(c, 400) for c in r[:MAX_COLS]] for r in rows[:MAX_ROWS]]
        rows = [r for r in rows if any(c for c in r)]
        if not rows:
            return None
        width = max(len(r) for r in rows)
        rows = [r + [''] * (width - len(r)) for r in rows]
        while width > 1 and all(not r[width - 1] for r in rows):
            rows = [r[:width - 1] for r in rows]
            width -= 1
        if header_rows is None:
            header_rows = 1 if len(rows) > 1 and all(not is_number(c) for c in rows[0] if c) and any(is_number(c) for r in rows[1:] for c in r) else (1 if len(rows) > 1 and all(rows[0]) else 0)
        text = '\n'.join(' | '.join(r) for r in rows[:200])
        return self.add('table', text, page=page, rows=rows, header_rows=header_rows, title=clip(title, 200) if title else None, **extra)

    def out(self):
        return {'format': self.format, 'parser': VERSION, 'pages': self.pages, 'title': clip(self.title, 300), 'blocks': self.blocks, 'vision': self.vision, 'notes': self.notes}


def _local(tag):
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _xml(data: bytes):
    if b'<!ENTITY' in data[:4096]:
        raise Failed('this file declares entities, which are not read')
    return ET.fromstring(data)


# ---------------------------------------------------------------------------------------------------------------------------------------------------- PDF
def pdf_pages(path: Path) -> int:
    text = run(['pdfinfo', str(path)], what='Reading the PDF', capture=True).decode('utf-8', 'replace')
    found = re.search(r'^Pages:\s+(\d+)', text, re.M)
    if not found:
        raise Failed('this PDF could not be read')
    return int(found.group(1))


def pdf_images(path: Path, last: int) -> dict:
    """page -> the largest share of the page one picture covers (from pdfimages' own table)."""
    try:
        listing = run(['pdfimages', '-list', '-f', '1', '-l', str(last), str(path)], what='Reading pictures', capture=True).decode('utf-8', 'replace')
    except Failed:
        return {}
    out = {}
    for line in listing.splitlines()[2:]:
        cols = line.split()
        if len(cols) < 14 or not cols[0].isdigit() or cols[2] in ('smask', 'mask'):
            continue
        try:
            page, w, h, xppi, yppi = int(cols[0]), int(cols[3]), int(cols[4]), float(cols[12]), float(cols[13])
        except ValueError:
            continue
        if xppi > 0 and yppi > 0:
            out[page] = max(out.get(page, 0.0), (w / xppi * 72) * (h / yppi * 72))
    return out


def pdf_layout(path: Path, last: int):
    data = run(['pdftotext', '-bbox-layout', '-enc', 'UTF-8', '-f', '1', '-l', str(last), str(path), '-'], what='Reading the PDF text', capture=True)
    data = re.sub(rb'<!DOCTYPE[^>]*>', b'', data, count=1)
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise Failed('the text of this PDF could not be read')
    pages = []
    for page in root.iter():
        if _local(page.tag) != 'page':
            continue
        width, height = float(page.get('width') or 1), float(page.get('height') or 1)
        lines = []
        for block_no, block in enumerate(e for e in page.iter() if _local(e.tag) == 'block'):
            for line in (e for e in block if _local(e.tag) == 'line'):
                words = [(w.text or '', float(w.get('xMin')), float(w.get('yMin')), float(w.get('xMax')), float(w.get('yMax'))) for w in line if _local(w.tag) == 'word']
                if words:
                    lines.append({'block': block_no, 'words': words, 'x0': min(w[1] for w in words), 'y0': min(w[2] for w in words), 'x1': max(w[3] for w in words),
                                  'y1': max(w[4] for w in words)})
        pages.append({'width': width, 'height': height, 'lines': lines})
    return pages


def _segments(line, gap):
    """A line split where words are far apart: the cells of a table row."""
    out, current = [], [line['words'][0]]
    for prev, word in zip(line['words'], line['words'][1:]):
        if word[1] - prev[3] > gap:
            out.append(current)
            current = []
        current.append(word)
    out.append(current)
    return [{'text': ' '.join(w[0] for w in seg), 'x0': seg[0][1], 'x1': seg[-1][3]} for seg in out]


def _table_regions(lines):
    """Runs of three or more rows whose words fall into the same three or more columns: tables drawn as text. -> list of (line indexes, rows)."""
    rows = []
    for i, line in enumerate(lines):
        height = max(1.0, line['y1'] - line['y0'])
        segs = _segments(line, gap=height * 1.2)
        rows.append((i, segs))
    regions, current = [], []

    def flush():
        if len(current) >= 3:
            counts = [len(s) for _, s in current]
            common = statistics.mode(counts)
            if common >= 3 and sum(1 for c in counts if abs(c - common) <= 1) >= 0.8 * len(counts):
                # Column positions from the rows that have every column; a row with an empty cell puts each piece under the column it starts nearest to.
                full = [s for _, s in current if len(s) == common]
                anchors = [statistics.median(s[c]['x0'] for s in full) for c in range(common)]
                rows = []
                for _, segs in current:
                    row = [''] * common
                    for seg in segs:
                        col = min(range(common), key=lambda c: abs(anchors[c] - seg['x0']))
                        row[col] = (row[col] + ' ' + seg['text']).strip()
                    rows.append(row)
                regions.append(([i for i, _ in current], rows))
        current.clear()
    for i, segs in rows:
        if len(segs) >= 3 or (current and len(segs) >= 2):
            current.append((i, segs))
        else:
            flush()
    flush()
    return regions


def parse_pdf(path: Path, doc: Doc, out_dir: Path):
    total = pdf_pages(path)
    doc.pages = total
    last = min(total, MAX_PAGES)
    if total > MAX_PAGES:
        doc.notes.append(f'only the first {MAX_PAGES} of {total} pages were read')
    pictures = pdf_images(path, last)
    layout = pdf_layout(path, last)
    heights = [l['y1'] - l['y0'] for p in layout for l in p['lines'] if l['y1'] > l['y0']]
    body = statistics.median(heights) if heights else 10.0
    for number, page in enumerate(layout, start=1):
        w, h, lines = page['width'], page['height'], page['lines']
        text_chars = sum(len(word[0]) for l in lines for word in l['words'])
        if text_chars < MIN_PAGE_TEXT:
            doc.vision.append({'page': number, 'why': 'no_text'})
            continue
        if pictures.get(number, 0) > FIGURE_SHARE * w * h:
            doc.vision.append({'page': number, 'why': 'figure'})
        # Tables drawn as text first: their lines are not paragraphs.
        lines.sort(key=lambda l: (round(l['y0'] / max(body, 1) / 0.6), l['x0']))
        merged = []
        for line in lines:                       # words on the same baseline from different flow blocks belong to one visual line (columns of a table)
            if merged and abs(line['y0'] - merged[-1]['y0']) < body * 0.45 and line['x0'] >= merged[-1]['x1']:
                prev = merged[-1]
                prev['words'] = prev['words'] + line['words']
                prev['x1'], prev['y1'] = max(prev['x1'], line['x1']), max(prev['y1'], line['y1'])
            else:
                merged.append(dict(line))
        used = set()
        tables = {}
        for indexes, rows in _table_regions(merged):
            first = merged[indexes[0]]
            tables[indexes[0]] = (rows, [min(merged[i]['x0'] for i in indexes) / w, first['y0'] / h, max(merged[i]['x1'] for i in indexes) / w, merged[indexes[-1]]['y1'] / h])
            used.update(indexes)
        # Then paragraphs: consecutive lines of the same flow block, split where the gap or the size changes.
        group = []

        def emit(group):
            if not group:
                return
            text = ' '.join(' '.join(w[0] for w in l['words']) for l in group)
            size = statistics.mean(l['y1'] - l['y0'] for l in group)
            bbox = [min(l['x0'] for l in group) / w, min(l['y0'] for l in group) / h, max(l['x1'] for l in group) / w, max(l['y1'] for l in group) / h]
            bbox = [round(v, 4) for v in bbox]
            if len(group) <= 2 and len(text) <= 160 and size >= body * 1.22 and not text.endswith(('.', ',', ';')):
                doc.add('heading', text, level=1 if size >= body * 1.75 else 2 if size >= body * 1.4 else 3, page=number, bbox=bbox)
                return
            marked = [l for l in group if BULLET.match(' '.join(w[0] for w in l['words']))]
            if marked and len(marked) >= max(1, len(group) // 3) and BULLET.match(' '.join(w[0] for w in group[0]['words'])):
                items = []
                for l in group:
                    line_text = ' '.join(w[0] for w in l['words'])
                    if BULLET.match(line_text) or not items:
                        items.append(BULLET.sub('', line_text))
                    else:
                        items[-1] += ' ' + line_text
                doc.add('list', '\n'.join(items), items=[clip(i, 600) for i in items[:300]], page=number, bbox=bbox)
                return
            doc.add('paragraph', text, page=number, bbox=bbox)
        for i, line in enumerate(merged):
            if i in tables:
                emit(group)
                group = []
                rows, bbox = tables[i]
                doc.table(rows, page=number, bbox=[round(v, 4) for v in bbox])
                continue
            if i in used:
                continue
            if group:
                prev = group[-1]
                size, prev_size = line['y1'] - line['y0'], prev['y1'] - prev['y0']
                if (line['y0'] - prev['y1'] > body * 0.9 or abs(size - prev_size) > body * 0.25 or line['block'] != prev['block']
                        or BULLET.match(' '.join(w[0] for w in line['words'])) and not BULLET.match(' '.join(w[0] for w in group[0]['words']))):
                    emit(group)
                    group = []
            group.append(line)
        emit(group)
    vision = doc.vision[:MAX_VISION_PAGES]
    if len(doc.vision) > MAX_VISION_PAGES:
        doc.notes.append(f'{len(doc.vision) - MAX_VISION_PAGES} pages with no text or with pictures were not read: there were too many')
        for item in doc.vision[MAX_VISION_PAGES:]:
            item['skipped'] = True
    for item in vision:
        name = f'page-{item["page"]:04d}'
        run(['pdftoppm', '-f', str(item['page']), '-l', str(item['page']), '-r', '110', '-scale-to', '1568', '-jpeg', '-jpegopt', 'quality=80', '-singlefile',
             str(path), str(out_dir / name)], what='Drawing a page')
        if (out_dir / (name + '.jpg')).exists():
            item['image'] = name + '.jpg'


# ---------------------------------------------------------------------------------------------------------------------------------------------------- Office files
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
P = '{http://schemas.openxmlformats.org/presentationml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
C = '{http://schemas.openxmlformats.org/drawingml/2006/chart}'
S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
PKG_REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'


def open_zip(path: Path) -> zipfile.ZipFile:
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise Failed('this file is damaged or is not what its name says')
    if sum(i.file_size for i in z.infolist()) > MAX_ZIP_BYTES:
        raise Failed('this file unpacks to too much to read')
    return z


def zread(z, name):
    try:
        return z.read(name)
    except KeyError:
        return None


def rels(z, part) -> dict:
    folder, base = part.rsplit('/', 1) if '/' in part else ('', part)
    data = zread(z, f'{folder}/_rels/{base}.rels' if folder else f'_rels/{base}.rels')
    if not data:
        return {}
    out = {}
    for rel in _xml(data):
        target = rel.get('Target') or ''
        if rel.get('TargetMode') == 'External':
            continue
        if target.startswith('/'):
            path = target.lstrip('/')
        else:
            parts = (folder.split('/') if folder else []) + target.split('/')
            stack = []
            for p in parts:
                if p == '..':
                    if stack:
                        stack.pop()
                elif p and p != '.':
                    stack.append(p)
            path = '/'.join(stack)
        out[rel.get('Id')] = path
    return out


def chart(z, part) -> dict | None:
    """A chart stored in an Office file: its own numbers, exactly as the file holds them (they are printed data, not estimates)."""
    data = zread(z, part)
    if not data:
        return None
    root = _xml(data)
    title_el = root.find(f'.//{C}title')
    title = ' '.join(t.text or '' for t in title_el.iter(A + 't')) if title_el is not None else ''
    plot = root.find(f'.//{C}plotArea')
    if plot is None:
        return None
    series, kind = [], ''
    for chart_el in plot:
        name = _local(chart_el.tag)
        if not name.endswith('Chart'):
            continue
        kind = kind or name[:-5]
        for ser in chart_el.findall(C + 'ser'):
            label_el = ser.find(f'{C}tx')
            label = ' '.join(v.text or '' for v in label_el.iter(C + 'v')) if label_el is not None else ''
            cat_el = ser.find(C + 'cat')
            val_el = ser.find(C + 'val') if ser.find(C + 'val') is not None else ser.find(C + 'yVal')
            cats = list(cat_el.iter(C + 'pt')) if cat_el is not None else []
            vals = list(val_el.iter(C + 'pt')) if val_el is not None else []
            names = {pt.get('idx'): (pt.findtext(C + 'v') or '') for pt in cats}
            points = [{'label': clip(names.get(pt.get('idx'), pt.get('idx')), 120), 'value': clip(pt.findtext(C + 'v') or '', 40), 'basis': 'printed'} for pt in vals[:500]]
            series.append({'name': clip(label, 120), 'points': points})
    if not series:
        return None
    return {'title': clip(title, 200), 'chart_type': kind, 'series': series[:30]}


def _chart_text(c):
    lines = [c['title']] if c['title'] else []
    for s in c['series']:
        lines.append((s['name'] + ': ' if s['name'] else '') + ', '.join(f"{p['label']} {p['value']}" for p in s['points'][:60]))
    return '\n'.join(lines)


def _grid(rows_cells):
    """Office table rows -> a rectangular grid with merged cells resolved: a cell spanning columns repeats its text; a cell continuing a vertical merge takes the text above."""
    grid = []
    for cells in rows_cells:
        row = []
        for text, span, vmerge in cells:
            col = len(row)
            if vmerge == 'continue' and grid:
                above = grid[-1]
                text = above[col] if col < len(above) else ''
            row.extend([text] * max(1, span))
        grid.append(row)
    return grid


def parse_docx(path: Path, doc: Doc):
    z = open_zip(path)
    body_xml = zread(z, 'word/document.xml')
    if not body_xml:
        raise Failed('this Word file has no text')
    styles = {}
    styles_xml = zread(z, 'word/styles.xml')
    if styles_xml:
        for st in _xml(styles_xml).iter(W + 'style'):
            name = (st.find(W + 'name').get(W + 'val') if st.find(W + 'name') is not None else '') or ''
            level = st.find(f'{W}pPr/{W}outlineLvl')
            styles[st.get(W + 'styleId')] = (name.lower(), int(level.get(W + 'val')) if level is not None and (level.get(W + 'val') or '').isdigit() else None)
    links = rels(z, 'word/document.xml')
    root = _xml(body_xml)
    body = root.find(W + 'body')
    page = [1]
    list_items, list_page = [], [1]

    def flush_list():
        if list_items:
            doc.add('list', '\n'.join(i for i in list_items), items=[clip(i, 600) for i in list_items[:300]], page=list_page[0], para=len(doc.blocks))
            list_items.clear()

    def text_of(p):
        parts = []
        for node in p.iter():
            tag = _local(node.tag)
            if tag == 't' and node.tag == W + 't':
                parts.append(node.text or '')
            elif tag == 'tab' and node.tag == W + 'tab':
                parts.append('\t')
            elif tag == 'br' and node.tag == W + 'br':
                if node.get(W + 'type') == 'page':
                    page[0] += 1
                else:
                    parts.append('\n')
            elif tag == 'lastRenderedPageBreak':
                page[0] += 1
        return ''.join(parts)

    def figures(p):
        for frame in p.iter():
            if _local(frame.tag) == 'chart' and frame.tag == C + 'chart':
                target = links.get(frame.get(R + 'id'))
                found = chart(z, target) if target else None
                if found:
                    doc.add('chart', _chart_text(found), page=page[0], source='data', **found)
            elif _local(frame.tag) == 'docPr':
                alt = frame.get('descr') or frame.get('title') or ''
                if alt and not any(_local(e.tag) == 'chart' for e in p.iter()):
                    doc.add('figure', alt, page=page[0], alt=clip(alt, 400))

    for node in list(body):
        tag = node.tag
        if tag == W + 'p':
            style = node.find(f'{W}pPr/{W}pStyle')
            style_name, level = styles.get(style.get(W + 'val') if style is not None else None, ('', None))
            numbered = node.find(f'{W}pPr/{W}numPr') is not None
            text = text_of(node).strip()
            heading = re.match(r'heading (\d)', style_name)
            figures(node)
            if not text:
                continue
            if style_name == 'title':
                flush_list()
                doc.title = doc.title or text
                doc.add('heading', text, level=1, page=page[0], para=len(doc.blocks))
            elif heading or level is not None and level < 6:
                flush_list()
                doc.add('heading', text, level=int(heading.group(1)) if heading else level + 1, page=page[0], para=len(doc.blocks))
            elif numbered or style_name.startswith('list'):
                if not list_items:
                    list_page[0] = page[0]
                list_items.append(text)
            else:
                flush_list()
                doc.add('paragraph', text, page=page[0], para=len(doc.blocks))
        elif tag == W + 'tbl':
            flush_list()
            rows, header = [], 0
            for tr in node.findall(W + 'tr'):
                cells = []
                for tc in tr.findall(W + 'tc'):
                    span = tc.find(f'{W}tcPr/{W}gridSpan')
                    vm = tc.find(f'{W}tcPr/{W}vMerge')
                    cells.append((' '.join(text_of(p).strip() for p in tc.findall(W + 'p')).strip(), int(span.get(W + 'val')) if span is not None and (span.get(W + 'val') or '').isdigit() else 1,
                                  None if vm is None else ('restart' if vm.get(W + 'val') == 'restart' else 'continue')))
                if tr.find(f'{W}trPr/{W}tblHeader') is not None and header == len(rows):
                    header += 1
                rows.append(cells)
            doc.table(_grid(rows), page=page[0], header_rows=header or None, para=len(doc.blocks))
    flush_list()
    doc.pages = page[0]
    doc.notes.append('page numbers in a Word file are where Word last laid the pages out; they can differ slightly from a printed copy')


def _ppt_text(body):
    paragraphs = []
    for p in body.findall(A + 'p'):
        text = ''.join((r.text or '') for r in p.iter(A + 't')).strip()
        if text:
            ppr = p.find(A + 'pPr')
            level = int(ppr.get('lvl') or 0) if ppr is not None and (ppr.get('lvl') or '0').isdigit() else 0
            bullet = ppr is not None and (ppr.find(A + 'buChar') is not None or ppr.find(A + 'buAutoNum') is not None)
            paragraphs.append((text, level, bullet))
    return paragraphs


def parse_pptx(path: Path, doc: Doc):
    z = open_zip(path)
    pres = zread(z, 'ppt/presentation.xml')
    if not pres:
        raise Failed('this PowerPoint file has no slides')
    links = rels(z, 'ppt/presentation.xml')
    order = [links.get(s.get(R + 'id')) for s in _xml(pres).iter(P + 'sldId')]
    order = [o for o in order if o][:MAX_PAGES]
    doc.pages = len(order)
    for number, part in enumerate(order, start=1):
        data = zread(z, part)
        if not data:
            continue
        slide_links = rels(z, part)
        root = _xml(data)

        def walk(tree):
            for shape in tree:
                tag = shape.tag
                if tag == P + 'grpSp':
                    walk(shape)
                elif tag == P + 'sp':
                    ph = shape.find(f'{P}nvSpPr/{P}nvPr/{P}ph')
                    kind = ph.get('type') if ph is not None else ''
                    body = shape.find(P + 'txBody')
                    if body is None:
                        continue
                    paras = _ppt_text(body)
                    if not paras:
                        continue
                    if kind in ('title', 'ctrTitle'):
                        text = ' '.join(t for t, _, _ in paras)
                        if number == 1 and not doc.title:
                            doc.title = text
                        doc.add('heading', text, level=1 if kind == 'ctrTitle' or number == 1 else 2, page=number)
                    elif kind != 'sldNum' and kind != 'dt' and kind != 'ftr':
                        if len(paras) > 1 and (any(b for _, _, b in paras) or kind in ('body', 'obj', '')):
                            doc.add('list', '\n'.join(t for t, _, _ in paras), items=[clip(t, 600) for t, _, _ in paras[:200]], page=number)
                        else:
                            doc.add('paragraph', ' '.join(t for t, _, _ in paras), page=number)
                elif tag == P + 'graphicFrame':
                    table = shape.find(f'.//{A}tbl')
                    if table is not None:
                        rows = []
                        for tr in table.findall(A + 'tr'):
                            cells = []
                            for tc in tr.findall(A + 'tc'):
                                if tc.get('hMerge') == '1':
                                    continue
                                text = ' '.join(''.join(t.text or '' for t in p.iter(A + 't')) for p in tc.iter(A + 'p')).strip()
                                cells.append((text, int(tc.get('gridSpan') or 1), 'continue' if tc.get('vMerge') == '1' else None))
                            rows.append(cells)
                        doc.table(_grid(rows), page=number)
                        continue
                    ref = shape.find(f'.//{C}chart')
                    if ref is not None:
                        found = chart(z, slide_links.get(ref.get(R + 'id')) or '')
                        if found:
                            doc.add('chart', _chart_text(found), page=number, source='data', **found)
                elif tag == P + 'pic':
                    alt = shape.find(f'{P}nvPicPr/{P}cNvPr')
                    words = (alt.get('descr') or alt.get('title') or '') if alt is not None else ''
                    doc.add('figure', words or 'A picture', page=number, alt=clip(words, 400))
        tree = root.find(f'{P}cSld/{P}spTree')
        if tree is not None:
            walk(tree)
        notes = next((t for t in slide_links.values() if 'notesSlide' in t), None)
        if notes and zread(z, notes):
            text = ' '.join(t.text or '' for t in _xml(zread(z, notes)).iter(A + 't') if (t.text or '').strip() and not (t.text or '').strip().isdigit())
            if text.strip():
                doc.add('notes', text, page=number)


DATE_FORMATS = set(range(14, 23)) | {45, 46, 47}


def _serial_date(value: float) -> str:
    try:
        moment = datetime(1899, 12, 30) + timedelta(days=float(value))
    except (OverflowError, ValueError):
        return str(value)
    return moment.strftime('%Y-%m-%d') if moment.hour == moment.minute == 0 else moment.strftime('%Y-%m-%d %H:%M')


def _cell_ref(ref):
    found = re.match(r'([A-Z]{1,3})(\d+)$', ref or '')
    if not found:
        return None
    col = 0
    for ch in found.group(1):
        col = col * 26 + ord(ch) - 64
    return int(found.group(2)) - 1, col - 1


def parse_xlsx(path: Path, doc: Doc):
    z = open_zip(path)
    book = zread(z, 'xl/workbook.xml')
    if not book:
        raise Failed('this Excel file has no sheets')
    shared = []
    strings = zread(z, 'xl/sharedStrings.xml')
    if strings:
        for si in _xml(strings).iter(S + 'si'):
            shared.append(''.join(t.text or '' for t in si.iter(S + 't')))
    date_styles = []
    styles = zread(z, 'xl/styles.xml')
    if styles:
        sroot = _xml(styles)
        custom = {int(f.get('numFmtId')): f.get('formatCode') or '' for f in sroot.iter(S + 'numFmt') if (f.get('numFmtId') or '').isdigit()}
        xfs = sroot.find(S + 'cellXfs')
        for xf in (xfs if xfs is not None else []):
            fid = int(xf.get('numFmtId') or 0)
            code = re.sub(r'"[^"]*"|\[[^\]]*\]', '', custom.get(fid, '')).lower()
            date_styles.append(fid in DATE_FORMATS or (fid in custom and bool(re.search(r'[dy]', code)) and 'h' not in code[:1]))
    links = rels(z, 'xl/workbook.xml')
    sheets = [(s.get('name') or f'Sheet {i + 1}', links.get(s.get(R + 'id'))) for i, s in enumerate(_xml(book).iter(S + 'sheet'))]
    doc.pages = len(sheets)
    for number, (name, part) in enumerate(sheets, start=1):
        data = zread(z, part) if part else None
        if not data:
            continue
        root = _xml(data)
        cells, width, height = {}, 0, 0
        for c in root.iter(S + 'c'):
            where = _cell_ref(c.get('r'))
            if where is None:
                continue
            row, col = where
            if row >= MAX_ROWS or col >= MAX_COLS:
                continue
            kind, value = c.get('t'), c.findtext(S + 'v')
            if kind == 's' and value is not None and value.isdigit() and int(value) < len(shared):
                text = shared[int(value)]
            elif kind == 'inlineStr':
                text = ''.join(t.text or '' for t in c.iter(S + 't'))
            elif kind == 'b':
                text = 'TRUE' if value == '1' else 'FALSE'
            elif value is not None:
                style = int(c.get('s') or 0)
                text = _serial_date(value) if kind in (None, 'n') and style < len(date_styles) and date_styles[style] and re.match(r'^-?\d+(\.\d+)?$', value) else value
                if re.match(r'^-?\d+\.\d{9,}$', text):
                    text = repr(round(float(text), 8))
            else:
                text = ''
            if text != '':
                cells[(row, col)] = text
                width, height = max(width, col + 1), max(height, row + 1)
        for merge in root.iter(S + 'mergeCell'):
            parts = (merge.get('ref') or '').split(':')
            if len(parts) == 2 and _cell_ref(parts[0]) and _cell_ref(parts[1]):
                (r0, c0), (r1, c1) = _cell_ref(parts[0]), _cell_ref(parts[1])
                value = cells.get((r0, c0), '')
                for r in range(r0, min(r1, MAX_ROWS - 1) + 1):
                    for cc in range(c0, min(c1, MAX_COLS - 1) + 1):
                        cells.setdefault((r, cc), value)
        if root.find(f'.//{S}dimension') is not None and height >= MAX_ROWS:
            doc.notes.append(f'sheet "{name}" has more rows than are read ({MAX_ROWS})')
        rows = [[cells.get((r, c), '') for c in range(width)] for r in range(height)]
        if rows:
            doc.add('heading', name, level=2, page=number)
            doc.table(rows, page=number, title=name, sheet=name)
    for part in sorted(n for n in z.namelist() if re.match(r'xl/charts/chart\d+\.xml$', n)):
        found = chart(z, part)
        if found:
            doc.add('chart', _chart_text(found), source='data', **found)


# ---------------------------------------------------------------------------------------------------------------------------------------------------- text formats
def decode(data: bytes) -> str:
    for codec in ('utf-8-sig', 'utf-16'):
        try:
            text = data.decode(codec)
            if codec == 'utf-16' and not data[:2] in (b'\xff\xfe', b'\xfe\xff'):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return data.decode('latin-1')


def parse_markdown(text: str, doc: Doc, *, markdown=True):
    lines = text.splitlines()
    para, items, table, code = [], [], [], None

    def flush(at):
        nonlocal para, items, table
        if para:
            doc.add('paragraph', ' '.join(para), line=at - len(para) + 1)
            para = []
        if items:
            doc.add('list', '\n'.join(items), items=[clip(i, 600) for i in items[:300]], line=at)
            items = []
        if table:
            rows = [[c.strip() for c in r.strip().strip('|').split('|')] for r in table if not re.match(r'^\s*\|?\s*:?-{2,}', r)]
            doc.table(rows, line=at, header_rows=1 if len(table) > 1 and re.match(r'^\s*\|?\s*:?-{2,}', table[1]) else None)
            table = []
    for n, line in enumerate(lines, start=1):
        if code is not None:
            if line.strip().startswith('```'):
                doc.add('code', '\n'.join(code), line=n - len(code))
                code = None
            else:
                code.append(line)
            continue
        if markdown and line.strip().startswith('```'):
            flush(n)
            code = []
            continue
        heading = re.match(r'^(#{1,6})\s+(.*)', line) if markdown else None
        if heading:
            flush(n)
            doc.add('heading', heading.group(2).strip('# '), level=len(heading.group(1)), line=n)
            doc.title = doc.title or heading.group(2).strip('# ')
        elif markdown and line.strip().startswith('|') and line.count('|') >= 2:
            if para or items:
                flush(n)
            table.append(line)
        elif BULLET.match(line):
            if para or table:
                flush(n)
            items.append(BULLET.sub('', line).strip())
        elif not line.strip():
            flush(n)
        elif items and line.startswith(('  ', '\t')):
            items[-1] += ' ' + line.strip()
        else:
            if items or table:
                flush(n)
            para.append(line.strip())
    if code:
        doc.add('code', '\n'.join(code), line=len(lines))
    flush(len(lines))
    doc.pages = None


class _Html(HTMLParser):
    SKIP = {'script', 'style', 'noscript', 'template', 'svg', 'head', 'iframe', 'object'}
    BLOCK = {'p', 'div', 'section', 'article', 'blockquote', 'td', 'th', 'li', 'br', 'tr', 'pre', 'dd', 'dt', 'figcaption'}

    def __init__(self, doc):
        super().__init__(convert_charrefs=True)
        self.doc, self.skip, self.buffer, self.heading, self.lists, self.items = doc, 0, [], None, 0, []
        self.table, self.row, self.cell, self.span, self.pre, self.title_open = None, None, None, 1, False, False

    def _flush(self):
        text = clip(' '.join(''.join(self.buffer).split()))
        self.buffer = []
        if not text:
            return
        if self.heading:
            self.doc.add('heading', text, level=self.heading)
        elif self.lists:
            self.items.append(text)
        else:
            self.doc.add('code' if self.pre else 'paragraph', text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in self.SKIP:
            self.skip += 1
            return
        if tag == 'title':
            self.title_open = True
            return
        if self.skip:
            return
        if self.cell is not None:
            if tag == 'br':
                self.cell.append(' ')
            return
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._flush()
            self.heading = int(tag[1])
        elif tag in ('ul', 'ol'):
            self._flush()
            self.lists += 1
        elif tag == 'table':
            self._flush()
            self.table = []
        elif tag == 'tr' and self.table is not None:
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell, self.span = [], int(attrs.get('colspan') or 1) if (attrs.get('colspan') or '1').isdigit() else 1
        elif tag == 'img' and (attrs.get('alt') or '').strip():
            self._flush()
            self.doc.add('figure', attrs['alt'], alt=clip(attrs['alt'], 400))
        elif tag == 'pre':
            self._flush()
            self.pre = True
        elif tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag == 'title':
            self.title_open = False
            return
        if self.skip:
            return
        if tag in ('td', 'th') and self.cell is not None:
            self.row.extend([clip(''.join(self.cell), 400)] * min(self.span, MAX_COLS))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == 'table' and self.table is not None:
            self.doc.table(self.table)
            self.table = None
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._flush()
            self.heading = None
        elif tag in ('ul', 'ol'):
            self._flush()
            self.lists = max(0, self.lists - 1)
            if not self.lists and self.items:
                self.doc.add('list', '\n'.join(self.items), items=[clip(i, 600) for i in self.items[:300]])
                self.items = []
        elif tag == 'pre':
            self._flush()
            self.pre = False
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if self.title_open:
            self.doc.title = clip((self.doc.title + ' ' + data).strip(), 300)
        elif self.skip:
            return
        elif self.cell is not None:
            self.cell.append(data)
        else:
            self.buffer.append(data)

    def close(self):
        super().close()
        self._flush()
        if self.items:
            self.doc.add('list', '\n'.join(self.items), items=self.items[:300])


def parse_html(text: str, doc: Doc):
    parser = _Html(doc)
    parser.feed(text)
    parser.close()


def parse_eml(data: bytes, doc: Doc):
    message = email.message_from_bytes(data, policy=email.policy.default)
    head = [f'{k}: {clip(message.get(k, ""), 400)}' for k in ('From', 'To', 'Cc', 'Date', 'Subject') if message.get(k)]
    doc.title = clip(message.get('Subject', ''), 300)
    if head:
        doc.add('header', '\n'.join(head))
    body = message.get_body(preferencelist=('plain', 'html'))
    if body is not None:
        try:
            content = body.get_content()
        except (LookupError, ValueError):
            content = ''
        if body.get_content_subtype() == 'html':
            parse_html(content, doc)
        else:
            parse_markdown(content, doc, markdown=False)
    names = [clip(p.get_filename() or 'attachment', 200) for p in message.iter_attachments()]
    if names:
        doc.add('list', 'Attachments:\n' + '\n'.join(names), items=names, title='Attachments')


def parse_csv(text: str, doc: Doc, delimiter=None):
    sample = text[:20000]
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=',;\t|').delimiter
        except csv.Error:
            delimiter = ','
    rows = []
    for row in csv.reader(io.StringIO(text), delimiter=delimiter):
        rows.append(row)
        if len(rows) >= MAX_ROWS:
            doc.notes.append(f'only the first {MAX_ROWS} rows were read')
            break
    doc.table(rows, page=1)
    doc.pages = 1


# ---------------------------------------------------------------------------------------------------------------------------------------------------- entry
def parse(source: Path, out_dir: Path) -> dict:
    kind = ext(source.name)
    with source.open('rb') as handle:
        data_head = handle.read(8)
    fmt = 'pdf' if data_head.startswith(b'%PDF-') else kind
    doc = Doc(fmt)
    if fmt == 'pdf':
        parse_pdf(source, doc, out_dir)
    elif fmt in ('docx',):
        parse_docx(source, doc)
    elif fmt in ('pptx',):
        parse_pptx(source, doc)
    elif fmt in ('xlsx',):
        parse_xlsx(source, doc)
    elif fmt in ('csv', 'tsv'):
        parse_csv(decode(source.read_bytes()), doc, '\t' if fmt == 'tsv' else None)
    elif fmt in ('html', 'htm'):
        parse_html(decode(source.read_bytes()), doc)
    elif fmt == 'eml':
        parse_eml(source.read_bytes(), doc)
    elif fmt in IMAGE_EXT:
        doc.pages = 1
        name = 'page-0001.' + ('jpg' if fmt == 'jpeg' else fmt)
        shutil.copyfile(source, out_dir / name)
        doc.vision.append({'page': 1, 'why': 'no_text', 'image': name})
    elif fmt in ('md', 'markdown'):
        parse_markdown(decode(source.read_bytes()), doc)
    elif fmt in ('txt', 'log', 'json', 'xml', 'yaml', 'yml', 'py', 'js', 'ts', 'tsx', 'jsx', 'css', 'sql', ''):
        text = decode(source.read_bytes())
        if fmt in ('txt', 'log', ''):
            parse_markdown(text, doc, markdown=False)
        else:
            for n, chunk in enumerate(re.split(r'\n\s*\n', text)):
                if chunk.strip():
                    doc.add('code', chunk, line=n + 1)
    else:
        raise Failed('this kind of file is not read')
    return doc.out()


def main(job='/job'):
    job = Path(job)
    out = job / 'out'
    try:
        request = json.loads((job / 'request.json').read_text())
        source = job / 'in' / str(request.get('source') or '')
        if not source.is_file() or source.is_symlink():
            raise Failed('invalid request')
        structure = parse(source, out)
        (out / 'structure.json').write_text(json.dumps(structure, ensure_ascii=False))
        (out / 'result.json').write_text(json.dumps({'ok': True, 'pages': structure['pages'], 'images': [v['image'] for v in structure['vision'] if v.get('image')]}))
    except Failed as exc:
        (out / 'result.json').write_text(json.dumps({'ok': False, 'error': str(exc)}))
    except Exception:
        (out / 'result.json').write_text(json.dumps({'ok': False, 'error': 'This file could not be read'}))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/job')
