"""The conversion engine. Runs INSIDE the renderer container (deploy/renderer/Dockerfile): no network, read-only root, no capabilities, one job, then gone.

Standard library plus the tools the image carries (LibreOffice, pandoc, Chromium, poppler, librsvg, openpyxl, Pillow). It never imports the platform.

A job is a folder:
    /job/request.json   {"source": "report.md", "target": "pdf", "preview": true}
    /job/in/...         the source and any files it refers to (images in a document), at their own relative paths
    /job/out/result.<target>, /job/out/preview.jpg, /job/out/result.json   written here

Everything in /job/in was written by an assistant from customer and web content: treat it as hostile. It is only ever handed to converters as data;
nothing in it is executed, and the container has nowhere to send anything.
"""
from __future__ import annotations
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TEXT = {'md', 'markdown', 'txt', 'html', 'htm', 'rst'}
WORD = {'docx', 'odt', 'rtf', 'doc'}
SHEET = {'xlsx', 'xls', 'ods', 'csv', 'tsv'}
SLIDES = {'pptx', 'ppt', 'odp'}
IMAGE = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tif', 'tiff'}
TARGETS = ('pdf', 'docx', 'odt', 'rtf', 'epub', 'html', 'md', 'txt', 'xlsx', 'xls', 'ods', 'csv', 'pptx', 'odp', 'png', 'jpg', 'webp', 'gif')
PANDOC_READ = {'md': 'gfm', 'markdown': 'gfm', 'txt': 'gfm', 'html': 'html', 'htm': 'html', 'rst': 'rst', 'docx': 'docx', 'odt': 'odt', 'rtf': 'rtf', 'epub': 'epub'}
PANDOC_WRITE = {'docx': 'docx', 'odt': 'odt', 'rtf': 'rtf', 'epub': 'epub', 'html': 'html', 'md': 'gfm', 'txt': 'plain', 'pptx': 'pptx'}
SOFFICE_FILTER = {'xlsx': 'xlsx:Calc MS Excel 2007 XML', 'xls': 'xls:MS Excel 97', 'ods': 'ods', 'csv': 'csv:Text - txt - csv (StarCalc):44,34,76,1',
                  'docx': 'docx:MS Word 2007 XML', 'odt': 'odt', 'rtf': 'rtf', 'pptx': 'pptx:Impress MS PowerPoint 2007 XML', 'odp': 'odp', 'pdf': 'pdf'}
STEP_SECONDS = 75
MAX_CELLS = 2_000_000
MAX_PIXELS = 60_000_000

# What a document printed from markdown or plain text looks like. Fonts are the ones the image installs; nothing is fetched.
PRINT_CSS = '''
@page { size: A4; margin: 20mm 18mm; }
html { font-family: "Noto Sans", "Noto Sans Arabic", "Noto Sans CJK SC", "DejaVu Sans", sans-serif; font-size: 11pt; line-height: 1.5; color: #1a1a1a; }
body { margin: 0; }
h1, h2, h3, h4 { line-height: 1.25; margin: 1.4em 0 .5em; page-break-after: avoid; }
h1 { font-size: 22pt; margin-top: 0; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }
p, ul, ol, table, pre, blockquote { margin: 0 0 .8em; }
table { border-collapse: collapse; width: 100%; font-size: 10pt; page-break-inside: auto; }
th, td { border: 1px solid #c8c8c8; padding: 5px 8px; text-align: start; vertical-align: top; }
th { background: #f0f0f0; font-weight: 600; } tr { page-break-inside: avoid; }
pre, code { font-family: "DejaVu Sans Mono", monospace; font-size: 9.5pt; }
pre { background: #f5f5f5; padding: 10px; border-radius: 4px; white-space: pre-wrap; word-break: break-word; }
blockquote { border-inline-start: 3px solid #c8c8c8; padding-inline-start: 12px; color: #444; }
img { max-width: 100%; } a { color: #1a4fa0; text-decoration: none; }
'''


class Failed(Exception):
    """A conversion that did not work, with a short reason safe to show the assistant (never a path or tool output)."""


def ext(name: str) -> str:
    return name.rsplit('.', 1)[-1].lower() if '.' in name else ''


def run(argv, cwd, *, what):
    """One converter, bounded in time, with a private writable home. Its output is never passed on: only whether it worked."""
    env = {'HOME': '/tmp/home', 'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8', 'TMPDIR': '/tmp', 'XDG_RUNTIME_DIR': '/tmp/run'}
    for folder in ('/tmp/home', '/tmp/run'):
        os.makedirs(folder, exist_ok=True)
    try:
        done = subprocess.run(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=STEP_SECONDS)
    except subprocess.TimeoutExpired:
        raise Failed(f'{what} took too long')
    except OSError:
        raise Failed(f'{what} is not available')
    if done.returncode != 0:
        raise Failed(f'{what} could not read this file')


def pandoc(source: Path, target: Path, read: str, write: str, extra=()):
    # --sandbox: pandoc reads only the files named on its command line (no includes, no network, no Lua filters from the document).
    run(['pandoc', '--sandbox', '-f', read, '-t', write, '-o', str(target), *extra, str(source)], source.parent, what='The document converter')
    return target


def soffice(source: Path, out_dir: Path, target: str):
    """LibreOffice, headless, with macros off and a throwaway profile. -> the converted file."""
    run(['soffice', '--headless', '--norestore', '--nolockcheck', '--nodefault', '--nofirststartwizard', '-env:UserInstallation=file:///tmp/lo',
         '--convert-to', SOFFICE_FILTER[target], '--outdir', str(out_dir), str(source)], source.parent, what='The office converter')
    made = out_dir / (source.stem + '.' + target)
    if not made.is_file() or made.stat().st_size == 0:
        raise Failed('The office converter could not read this file')
    return made


def chromium(source: Path, target: Path, *, pdf: bool):
    """Headless Chromium on a local file. The container has no network, so a page can load only what is beside it."""
    how = ['--print-to-pdf=' + str(target), '--no-pdf-header-footer'] if pdf else ['--screenshot=' + str(target), '--window-size=1280,1600', '--hide-scrollbars']
    run(['chromium', '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-extensions', '--disable-background-networking',
         '--user-data-dir=/tmp/chrome', '--virtual-time-budget=8000', *how, source.resolve().as_uri()], source.parent, what='The page printer')
    if not target.is_file() or target.stat().st_size == 0:
        raise Failed('The page printer produced nothing')
    return target


def to_html(source: Path, work: Path) -> Path:
    """Markdown or text as a standalone printable page, written beside the source so its relative images still resolve."""
    kind = ext(source.name)
    if kind in ('html', 'htm'):
        return source
    css = work / 'print.css'
    css.write_text(PRINT_CSS)
    page = source.with_name(source.stem + '.lumina-print.html')
    pandoc(source, page, PANDOC_READ[kind], 'html', ['--standalone', '--embed-resources', '--css', str(css), '--metadata', 'pagetitle=' + source.stem, '--metadata', 'dir=auto'])
    return page


# ---- spreadsheets ----------------------------------------------------------------------------------------------------------------------------

NUMBER = re.compile(r'^-?(?:\d{1,15}|\d{1,15}\.\d{1,10})$')


def typed(value: str):
    """A CSV cell as the value a person would expect in a sheet: plain numbers become numbers; everything else (ids with leading zeros, dates, text) stays as written."""
    text = value.strip()
    if NUMBER.fullmatch(text) and not (len(text.lstrip('-')) > 1 and text.lstrip('-').startswith('0') and '.' not in text):
        return float(text) if '.' in text else int(text)
    return value


def style_sheet(sheet, widths=None, formats=None, header=True):
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    if header and sheet.max_row >= 1:
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill('solid', fgColor='EDEDED')
            cell.alignment = Alignment(vertical='center', wrap_text=True)
        sheet.freeze_panes = 'A2'
        if sheet.max_row > 1 and sheet.max_column >= 1:
            sheet.auto_filter.ref = sheet.dimensions
    sizes = {}
    for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 500)):
        for cell in row:
            if cell.value is not None:
                sizes[cell.column] = max(sizes.get(cell.column, 0), min(len(str(cell.value)), 60))
    for column, size in sizes.items():
        sheet.column_dimensions[get_column_letter(column)].width = max(8, size + 2)
    for index, width in enumerate(widths or [], start=1):
        if isinstance(width, (int, float)) and 2 <= width <= 120:
            sheet.column_dimensions[get_column_letter(index)].width = width
    for column, pattern in (formats or {}).items():
        if isinstance(column, str) and re.fullmatch(r'[A-Z]{1,3}', column) and isinstance(pattern, str) and len(pattern) <= 60:
            for cell in sheet[column][1 if header else 0:]:
                cell.number_format = pattern


def csv_to_xlsx(source: Path, target: Path):
    """A CSV as a real workbook. Cells are data: a cell that starts with '=' stays text (a formula belongs in a sheet description, see spec_to_xlsx)."""
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    text = source.read_bytes().decode('utf-8-sig', errors='replace')
    delimiter = '\t' if ext(source.name) == 'tsv' else ','
    if delimiter == ',':
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=',;\t|').delimiter
        except csv.Error:
            pass
    book = Workbook()
    sheet = book.active
    sheet.title = (re.sub(r'[\[\]:*?/\\]', ' ', source.stem)[:31] or 'Sheet1')
    cells = 0
    for row in csv.reader(io.StringIO(text), delimiter=delimiter):
        cells += len(row)
        if cells > MAX_CELLS:
            raise Failed('The table is too large for one workbook')
        out = []
        for value in row:
            value = typed(ILLEGAL_CHARACTERS_RE.sub('', value))
            out.append(value)
        sheet.append(out)
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str) and cell.value.startswith('='):
                cell.data_type = 's'
    style_sheet(sheet)
    book.save(target)
    return target


def spec_to_xlsx(source: Path, target: Path):
    """A workbook from a description: {"sheets": [{"name", "columns": [...], "rows": [[...]], "widths": [...], "formats": {"B": "#,##0.00"}}]}.
    A string cell that starts with '=' is a formula."""
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    try:
        spec = json.loads(source.read_bytes().decode('utf-8-sig'))
    except ValueError:
        raise Failed('The sheet description is not valid JSON')
    sheets = spec.get('sheets') if isinstance(spec, dict) else None
    if isinstance(spec, list):                      # a bare list of records: [{"Month": "Jan", "Revenue": 1200}, ...]
        records = [r for r in spec if isinstance(r, dict)]
        columns = list(dict.fromkeys(k for r in records for k in r))
        sheets = [{'name': source.stem, 'columns': columns, 'rows': [[r.get(c) for c in columns] for r in records]}]
    if not isinstance(sheets, list) or not sheets or len(sheets) > 50:
        raise Failed('Give "sheets": a list of 1 to 50 sheets, each with "columns" and "rows"')
    book = Workbook()
    book.remove(book.active)
    cells = 0
    for index, item in enumerate(sheets, start=1):
        if not isinstance(item, dict) or not isinstance(item.get('rows'), list):
            raise Failed('Every sheet needs "rows": a list of rows')
        name = re.sub(r'[\[\]:*?/\\]', ' ', str(item.get('name') or f'Sheet{index}'))[:31] or f'Sheet{index}'
        sheet = book.create_sheet(name if name not in book.sheetnames else f'{name[:27]} {index}')
        columns = item.get('columns')
        rows = ([columns] if isinstance(columns, list) and columns else []) + item['rows']
        for row in rows:
            if not isinstance(row, list):
                raise Failed('Every row must be a list of cells')
            cells += len(row)
            if cells > MAX_CELLS:
                raise Failed('The workbook is too large')
            sheet.append([ILLEGAL_CHARACTERS_RE.sub('', v) if isinstance(v, str) else v if isinstance(v, (int, float, bool)) or v is None else str(v) for v in row])
        style_sheet(sheet, item.get('widths'), item.get('formats') if isinstance(item.get('formats'), dict) else None, header=bool(isinstance(columns, list) and columns))
    book.save(target)
    return target


# ---- images ----------------------------------------------------------------------------------------------------------------------------------

def open_image(source: Path, work: Path):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    if ext(source.name) == 'svg':
        flat = work / 'svg.png'
        run(['rsvg-convert', '--keep-aspect-ratio', '--width', '1600', '-o', str(flat), str(source)], source.parent, what='The drawing converter')
        source = flat
    try:
        image = Image.open(source)
        image.load()
    except Exception:
        raise Failed('The image could not be read')
    return image


def save_image(image, target: Path, kind: str):
    kind = 'jpeg' if kind in ('jpg', 'jpeg') else kind
    if kind in ('jpeg', 'pdf') and image.mode not in ('RGB', 'L'):
        flat = image.convert('RGBA')
        from PIL import Image
        background = Image.new('RGB', flat.size, (255, 255, 255))
        background.paste(flat, mask=flat.split()[-1])
        image = background
    try:
        image.save(target, format=kind.upper(), **({'quality': 90} if kind == 'jpeg' else {}))
    except Exception:
        raise Failed('The image could not be written in that format')
    return target


def pdf_page(source: Path, target_stem: Path, *, dpi: int, kind='png'):
    run(['pdftoppm', '-f', '1', '-l', '1', '-r', str(dpi), '-singlefile', '-jpeg' if kind == 'jpeg' else '-png', str(source), str(target_stem)], source.parent, what='The page reader')
    made = target_stem.with_suffix('.jpg' if kind == 'jpeg' else '.png')
    if not made.is_file():
        raise Failed('The page reader produced nothing')
    return made


def pdf_pages(source: Path):
    try:
        out = subprocess.run(['pdfinfo', str(source)], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL).stdout
        found = re.search(r'^Pages:\s+(\d+)', out, re.M)
        return int(found.group(1)) if found else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


# ---- the routes ------------------------------------------------------------------------------------------------------------------------------

def to_pdf(source: Path, work: Path) -> Path:
    kind = ext(source.name)
    out = work / 'as.pdf'
    if kind == 'pdf':
        return source
    if kind in TEXT:
        return chromium(to_html(source, work), out, pdf=True)
    if kind in WORD | SHEET | SLIDES:
        return soffice(source, work, 'pdf')
    if kind in IMAGE or kind == 'svg':
        return save_image(open_image(source, work), out, 'pdf')
    raise Failed(f'A .{kind} file cannot be turned into a PDF')


def convert(source: Path, target: str, work: Path) -> Path:
    kind = ext(source.name)
    out = work / ('result.' + target)
    if target == 'pdf':
        made = to_pdf(source, work)
        if made == source:
            raise Failed('The file is already a PDF')
        return made
    if target in ('png', 'jpg', 'webp', 'gif'):
        if kind in IMAGE or kind == 'svg':
            return save_image(open_image(source, work), out, target)
        if kind in ('html', 'htm') and target == 'png':
            return chromium(source, out, pdf=False)
        page = pdf_page(to_pdf(source, work), work / 'page', dpi=150)
        return page if target == 'png' else save_image(open_image(page, work), out, target)
    if target == 'xlsx' and kind in ('csv', 'tsv'):
        return csv_to_xlsx(source, out)
    if target in ('xlsx', 'csv') and kind == 'json':
        book = spec_to_xlsx(source, work / 'spec.xlsx')
        return book.rename(out) if target == 'xlsx' else soffice(book, work, 'csv')
    if target in ('xlsx', 'xls', 'ods', 'csv') and kind in SHEET:
        return soffice(source, work, target)
    if target in ('pptx', 'odp') and kind in SLIDES:
        return soffice(source, work, target)
    if target == 'pptx' and kind in ('md', 'markdown'):
        return pandoc(source, out, 'gfm', 'pptx')
    if target in ('txt', 'md') and kind == 'pdf':
        run(['pdftotext', '-layout', str(source), str(out)], source.parent, what='The page reader')
        return out
    if target in PANDOC_WRITE and kind in PANDOC_READ:
        extra = ['--standalone', '--embed-resources', '--metadata', 'pagetitle=' + source.stem] if target == 'html' else ['--metadata', 'dir=auto'] if target in ('docx', 'odt') else []
        return pandoc(source, out, PANDOC_READ[kind], PANDOC_WRITE[target], extra)
    if target in ('docx', 'odt', 'rtf') and kind in WORD:
        return soffice(source, work, target)
    raise Failed(f'A .{kind} file cannot be turned into .{target}')


def preview(made: Path, work: Path) -> Path | None:
    """A small picture of the first page, so the assistant can look at what it made before the customer does. Best-effort."""
    kind = ext(made.name)
    try:
        if kind in IMAGE:
            image = open_image(made, work)
        elif kind == 'pdf' or kind in WORD | SHEET | SLIDES:
            space = work / 'preview'
            space.mkdir(exist_ok=True)
            image = open_image(pdf_page(made if kind == 'pdf' else soffice(made, space, 'pdf'), space / 'first', dpi=70, kind='jpeg'), work)
        else:
            return None
        image.thumbnail((1100, 1400))
        return save_image(image, work / 'preview.jpg', 'jpeg')
    except Failed:
        return None


def main(job='/job'):
    job = Path(job)
    out_dir = job / 'out'
    result = {'ok': False, 'error': 'The conversion failed'}
    try:
        request = json.loads((job / 'request.json').read_text())
        target, name = request.get('target'), request.get('source')
        work = Path('/tmp/work')
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        # Work on a private copy: converters write beside their input, and /job/in is read-only.
        stage = work / 'in'
        shutil.copytree(job / 'in', stage, symlinks=False)
        source = (stage / str(name)).resolve()
        if stage.resolve() not in source.parents or not source.is_file() or source.is_symlink():
            raise Failed('The source file is missing')
        if target is None:                                   # preview only
            made = source
        elif target not in TARGETS:
            raise Failed(f'.{target} is not a format this converter writes')
        else:
            made = convert(source, target, work)
            if not made.is_file() or made.stat().st_size == 0:
                raise Failed('The conversion produced an empty file')
            shutil.copyfile(made, out_dir / ('result.' + target))
        result = {'ok': True, 'file': ('result.' + target) if target else None, 'pages': pdf_pages(made) if ext(made.name) == 'pdf' else None, 'preview': None}
        if request.get('preview', True):
            shot = preview(made, work)
            if shot is not None and shot.stat().st_size <= 2_000_000:
                shutil.copyfile(shot, out_dir / 'preview.jpg')
                result['preview'] = 'preview.jpg'
    except Failed as error:
        result = {'ok': False, 'error': str(error)}
    except Exception:
        result = {'ok': False, 'error': 'The conversion failed'}
    (out_dir / 'result.json').write_text(json.dumps(result))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:2]))
