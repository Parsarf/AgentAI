"""Small documents built in code for the knowledge tests (roadmap Phase 4): one of every format the parser reads, with known contents.

Nothing here is a real customer's document. The contract, the invoice and the meeting fixtures are invented and say so in their text.
"""
from __future__ import annotations
import io
import zipfile
import zlib


# ---------------------------------------------------------------------------------------------------------------------------------------------------- PDF
def _esc(text):
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def pdf(pages, *, scanned=()):
    """pages: a list of pages, each a list of (x, y, size, text). Page numbers (1-based) in `scanned` carry only a picture (no text layer)."""
    objects = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)
    font = add(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    kids = []
    pages_id = len(objects) + 1 + 2 * len(pages) + len(scanned) + 1          # placeholder, fixed below
    page_ids = []
    contents = []
    for n, lines in enumerate(pages, start=1):
        if n in scanned:
            w, h = 60, 30
            raw = b''.join(bytes([(x * 4 + y * 3) % 255]) * 3 for y in range(h) for x in range(w))
            data = zlib.compress(raw)
            image = add(b'<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n'
                        % (w, h, len(data)) + data + b'\nendstream')
            stream = b'q 500 0 0 700 50 50 cm /Im1 Do Q'
            content = add(b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream')
            contents.append((content, b'<< /XObject << /Im1 %d 0 R >> >>' % image))
        else:
            ops = []
            for x, y, size, text in lines:
                ops.append(f'BT /F1 {size} Tf {x} {y} Td ({_esc(text)}) Tj ET')
            stream = '\n'.join(ops).encode('latin-1')
            content = add(b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream')
            contents.append((content, b'<< /Font << /F1 %d 0 R >> >>' % font))
    first_page = len(objects) + 1
    pages_id = first_page + len(pages)
    for content, resources in contents:
        page_ids.append(add(b'<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Contents %d 0 R /Resources %s >>' % (pages_id, content, resources)))
    add(b'<< /Type /Pages /Kids [%s] /Count %d >>' % (b' '.join(b'%d 0 R' % p for p in page_ids), len(page_ids)))
    catalog = add(b'<< /Type /Catalog /Pages %d 0 R >>' % pages_id)
    out = io.BytesIO()
    out.write(b'%PDF-1.4\n')
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b'%d 0 obj\n' % i + body + b'\nendobj\n')
    xref = out.tell()
    out.write(b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1))
    for off in offsets:
        out.write(b'%010d 00000 n \n' % off)
    out.write(b'trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, catalog, xref))
    return out.getvalue()


CONTRACT_V1 = [
    [(72, 720, 22, 'Service Agreement (invented test document)'),
     (72, 680, 14, '1. Term'),
     (72, 660, 11, 'This agreement starts on 1 March 2026 and runs for twelve months.'),
     (72, 645, 11, 'Either party may end it with thirty days written notice.'),
     (72, 610, 14, '2. Fees'),
     (72, 590, 11, 'The monthly fee is 1,200 dollars, paid by the fifth day of each month.'),
     (72, 575, 11, 'Late payments carry a fee of 2 percent.'),
     (72, 540, 14, '3. Confidentiality'),
     (72, 520, 11, 'Both parties keep the other party information confidential for five years.')],
    [(72, 720, 14, '4. Price list'),
     (72, 690, 11, 'Item'), (260, 690, 11, 'Units'), (400, 690, 11, 'Price'),
     (72, 672, 11, 'Setup'), (260, 672, 11, '1'), (400, 672, 11, '500'),
     (72, 654, 11, 'Support'), (260, 654, 11, '12'), (400, 654, 11, '1,200'),
     (72, 636, 11, 'Training'), (260, 636, 11, '3'), (400, 636, 11, '300'),
     (72, 618, 11, 'Total'), (260, 618, 11, ''), (400, 618, 11, '2,000')],
]
CONTRACT_V2 = [
    [(72, 720, 22, 'Service Agreement (invented test document)'),
     (72, 680, 14, '1. Term'),
     (72, 660, 11, 'This agreement starts on 1 March 2026 and runs for twelve months.'),
     (72, 645, 11, 'Either party may end it with sixty days written notice.'),
     (72, 610, 14, '2. Fees'),
     (72, 590, 11, 'The monthly fee is 1,450 dollars, paid by the fifth day of each month.'),
     (72, 540, 14, '3. Confidentiality'),
     (72, 520, 11, 'Both parties keep the other party information confidential for five years.'),
     (72, 500, 11, 'Late payments carry a fee of 2 percent.')],
]


# ---------------------------------------------------------------------------------------------------------------------------------------------------- Office
def _zip(files: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(name, body)
    return out.getvalue()


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def docx(paragraphs):
    """paragraphs: ('h1'|'h2'|'p'|'li'|'pagebreak', text) or ('table', rows) where a cell may be ('text', span) or ('', 'continue')."""
    body = []
    for kind, value in paragraphs:
        if kind == 'table':
            rows = []
            for r, row in enumerate(value):
                cells = []
                for cell in row:
                    text, extra = (cell, '') if isinstance(cell, str) else cell
                    props = ''
                    if isinstance(extra, int):
                        props = f'<w:tcPr><w:gridSpan w:val="{extra}"/></w:tcPr>'
                    elif extra == 'continue':
                        props = '<w:tcPr><w:vMerge/></w:tcPr>'
                    elif extra == 'restart':
                        props = '<w:tcPr><w:vMerge w:val="restart"/></w:tcPr>'
                    cells.append(f'<w:tc>{props}<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>')
                header = '<w:trPr><w:tblHeader/></w:trPr>' if r == 0 else ''
                rows.append(f'<w:tr>{header}{"".join(cells)}</w:tr>')
            body.append(f'<w:tbl>{"".join(rows)}</w:tbl>')
        elif kind == 'pagebreak':
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        else:
            style = {'h1': 'Heading1', 'h2': 'Heading2', 'title': 'Title'}.get(kind)
            ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ('<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>' if kind == 'li' else '')
            body.append(f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{value}</w:t></w:r></w:p>')
    styles = (f'<w:styles {W}><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/></w:style><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/></w:style></w:styles>')
    return _zip({'[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
                 'word/document.xml': f'<w:document {W}><w:body>{"".join(body)}</w:body></w:document>', 'word/styles.xml': styles})


def pptx(slides):
    """slides: list of (title, [bullets], table rows or None)."""
    ns = ('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
    files = {}
    ids, rels = [], []
    for n, (title, bullets, table) in enumerate(slides, start=1):
        shapes = [f'<p:sp><p:nvSpPr><p:cNvPr id="1" name="t"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp>']
        if bullets:
            paras = ''.join(f'<a:p><a:pPr><a:buChar char="-"/></a:pPr><a:r><a:t>{b}</a:t></a:r></a:p>' for b in bullets)
            shapes.append(f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="b"/><p:cNvSpPr/><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr><p:txBody>{paras}</p:txBody></p:sp>')
        if table:
            rows = ''.join('<a:tr>' + ''.join(f'<a:tc><a:txBody><a:p><a:r><a:t>{c}</a:t></a:r></a:p></a:txBody></a:tc>' for c in row) + '</a:tr>' for row in table)
            shapes.append(f'<p:graphicFrame><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl>{rows}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>')
        files[f'ppt/slides/slide{n}.xml'] = f'<p:sld {ns}><p:cSld><p:spTree>{"".join(shapes)}</p:spTree></p:cSld></p:sld>'
        ids.append(f'<p:sldId id="{255 + n}" r:id="rId{n}"/>')
        rels.append(f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{n}.xml"/>')
    files['ppt/presentation.xml'] = f'<p:presentation {ns}><p:sldIdLst>{"".join(ids)}</p:sldIdLst></p:presentation>'
    files['ppt/_rels/presentation.xml.rels'] = f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(rels)}</Relationships>'
    files['[Content_Types].xml'] = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
    return _zip(files)


def xlsx(sheets, *, chart=None):
    """sheets: {name: rows}; a number is written as a number. `chart`: (title, [(label, value)]) adds a bar chart part."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    shared, files, entries, rels = [], {}, [], []
    for n, (name, rows) in enumerate(sheets.items(), start=1):
        out = []
        for r, row in enumerate(rows, start=1):
            cells = []
            for c, value in enumerate(row):
                ref = chr(65 + c) + str(r)
                if isinstance(value, (int, float)):
                    cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                else:
                    shared.append(str(value))
                    cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
            out.append(f'<row r="{r}">{"".join(cells)}</row>')
        files[f'xl/worksheets/sheet{n}.xml'] = f'<worksheet {ns}><sheetData>{"".join(out)}</sheetData></worksheet>'
        entries.append(f'<sheet name="{name}" sheetId="{n}" r:id="rId{n}"/>')
        rels.append(f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{n}.xml"/>')
    files['xl/workbook.xml'] = f'<workbook {ns}><sheets>{"".join(entries)}</sheets></workbook>'
    files['xl/_rels/workbook.xml.rels'] = f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(rels)}</Relationships>'
    files['xl/sharedStrings.xml'] = f'<sst {ns}>' + ''.join(f'<si><t>{s}</t></si>' for s in shared) + '</sst>'
    if chart:
        title, points = chart
        cats = ''.join(f'<c:pt idx="{i}"><c:v>{label}</c:v></c:pt>' for i, (label, _) in enumerate(points))
        vals = ''.join(f'<c:pt idx="{i}"><c:v>{value}</c:v></c:pt>' for i, (_, value) in enumerate(points))
        files['xl/charts/chart1.xml'] = ('<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                                         f'<c:chart><c:title><c:tx><c:rich><a:p><a:r><a:t>{title}</a:t></a:r></a:p></c:rich></c:tx></c:title><c:plotArea><c:barChart>'
                                         f'<c:ser><c:tx><c:v>Revenue</c:v></c:tx><c:cat><c:strRef><c:strCache>{cats}</c:strCache></c:strRef></c:cat>'
                                         f'<c:val><c:numRef><c:numCache>{vals}</c:numCache></c:numRef></c:val></c:ser></c:barChart></c:plotArea></c:chart></c:chartSpace>')
    files['[Content_Types].xml'] = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
    return _zip(files)


def eml(subject, sender, body, attachments=()):
    from email.message import EmailMessage
    message = EmailMessage()
    message['Subject'], message['From'], message['To'], message['Date'] = subject, sender, 'customer@example.test', 'Mon, 16 Nov 2026 09:00:00 +0000'
    message.set_content(body)
    for name, data in attachments:
        message.add_attachment(data, maintype='application', subtype='octet-stream', filename=name)
    return bytes(message)


MARKDOWN = b'''# Travel policy (invented test document)

Staff book travel through the travel desk.

## Hotels

- Up to 180 dollars a night in most cities
- Up to 260 dollars a night in London and New York

## Meals

| Meal | Limit |
|------|-------|
| Breakfast | 20 |
| Lunch | 30 |
| Dinner | 60 |
'''

HTML = b'''<html><head><title>Opening hours</title><script>alert(1)</script></head><body>
<h1>Opening hours (invented)</h1><p>The office is open from 9 to 5 on weekdays.</p>
<ul><li>Closed on public holidays</li><li>Open until 8 on Thursdays</li></ul>
<table><tr><th>Day</th><th>Hours</th></tr><tr><td>Monday</td><td>9-5</td></tr><tr><td colspan="2">Weekend closed</td></tr></table>
<img src="https://tracker.example/pixel.gif" alt="A map of the office">
</body></html>'''

CSV = b'Invoice,Customer,Amount\nINV-1,Acme,100\nINV-2,Globex,250.50\nINV-3,Initech,49.50\nTotal,,400\n'
