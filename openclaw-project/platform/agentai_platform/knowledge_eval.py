"""The knowledge evaluation set (roadmap Phase 4 exit gate 1; #33, #35, #36, #37, #45, #47, #31).

Real-looking business documents in every format the reader handles, each with known answers. Every document is invented and says so. It runs in two places:

* the test suite (`tests/test_knowledge_eval.py`), with the in-process reader and the deterministic stand-in embedder: a regression gate in CI;
* the live proof on the server (`deploy/phase45_live.py`), with the sealed reader in the render service, the vision model, the self-hosted embedding model and the
  PostgreSQL index: the measurement the targets come from.

    report = run(service, principal, add, wait=...)

`add(name, data) -> source id` puts one document in the index the way a customer's upload goes in; `wait()` lets the worker read what was added. The report holds numbers
only (and the questions that missed): recall at 5 and 10, citation correctness, table cell accuracy, comparison, planted conflicts, planted unsupported claims, search time.
"""
from __future__ import annotations
import re
import statistics
import time

from . import knowledge_samples as S

NOTE = '(invented evaluation document)'


# ------------------------------------------------------------------------------------------------------------------------------------- writing documents
def _md(title, *sections) -> bytes:
    parts = [f'# {title} {NOTE}', '']
    for heading, body in sections:
        parts += [f'## {heading}', '', body.strip(), '']
    return '\n'.join(parts).encode()


def _pdf_text(pages):
    """pages: [[('h', text) | ('p', text) | ('t', [[cells]], [x positions])]] -> a PDF with a text layer, laid out top to bottom."""
    out = []
    for page in pages:
        y, lines = 740, []
        for item in page:
            if item[0] == 'h':
                lines.append((72, y, 15, item[1])); y -= 26
            elif item[0] == 'p':
                for chunk in _wrap(item[1], 92):
                    lines.append((72, y, 11, chunk)); y -= 15
                y -= 8
            else:
                _kind, rows, xs = item
                for row in rows:
                    for x, cell in zip(xs, row):
                        lines.append((x, y, 11, cell))
                    y -= 18
                y -= 10
        out.append(lines)
    return S.pdf(out)


def _wrap(text, width):
    words, line, out = text.split(), '', []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line); line = w
        else:
            line = f'{line} {w}'.strip()
    return out + ([line] if line else [])


def _csv(rows) -> bytes:
    return ('\n'.join(','.join(f'"{c}"' if ',' in str(c) else str(c) for c in r) for r in rows) + '\n').encode()


# ------------------------------------------------------------------------------------------------------------------------------------------- the corpus
INVOICE_NORTHWIND = [['Description', 'Quantity', 'Unit price', 'Amount'],
                     ['Pallet racking, 2 m', '12', '145.00', '1,740.00'],
                     ['Installation', '1', '650.00', '650.00'],
                     ['Safety inspection', '1', '220.00', '220.00'],
                     ['Subtotal', '', '', '2,610.00'],
                     ['VAT 23%', '', '', '600.30'],
                     ['Total due', '', '', '3,210.30']]
INVOICE_CONTOSO = [['Item', 'Hours', 'Rate', 'Amount'],
                   ['Data migration', '32', '95', '3040'],
                   ['Training session', '6', '120', '720'],
                   ['Project management', '10', '85', '850'],
                   ['Total', '', '', '4610']]
PRICE_LIST = [['Product', 'Code', 'Unit', 'Price 2027'],
              ['Copy paper A4', 'P-100', 'box of 5 reams', '24.90'], ['Copy paper A3', 'P-110', 'box of 5 reams', '41.50'],
              ['Toner black', 'T-200', 'cartridge', '68.00'], ['Toner colour', 'T-210', 'cartridge', '89.00'],
              ['Stapler', 'S-300', 'piece', '12.40'], ['Staples 26/6', 'S-310', 'box of 5000', '3.20'],
              ['Desk lamp', 'L-400', 'piece', '34.00'], ['Monitor arm', 'M-500', 'piece', '79.00'],
              ['Ergonomic chair', 'C-600', 'piece', '289.00'], ['Standing desk', 'D-700', 'piece', '499.00'],
              ['Whiteboard 120x90', 'W-800', 'piece', '115.00'], ['Markers, set of 4', 'W-810', 'set', '6.80']]
STATEMENT = [['Line', 'Q3 2026', 'Q3 2025'],
             ['Revenue', 1284000, 1102500], ['Cost of sales', 512400, 468900], ['Gross profit', 771600, 633600],
             ['Operating expenses', 498200, 455100], ['Operating profit', 273400, 178500], ['Tax', 61000, 40100], ['Net income', 212400, 138400]]


def corpus() -> list[tuple[str, bytes]]:
    lease_p1 = [('h', f'Residential Lease Agreement {NOTE}'),
                ('p', 'This lease is between Marta Silva, the landlord, and Daniel Okafor, the tenant, for the flat at Rua das Flores 12, 3rd floor, Lisbon.'),
                ('h', '1. Rent'),
                ('p', 'The monthly rent is 1,350 euros, payable by bank transfer on or before the first day of each month. A late payment fee of 5 percent applies after the tenth day.'),
                ('h', '2. Deposit'),
                ('p', 'The tenant pays a security deposit equal to two months of rent before moving in. It is returned within 30 days of the end of the lease, less any agreed repair costs.')]
    lease_p2 = [('h', '3. Ending the lease'),
                ('p', 'Either party may end this lease by giving sixty days of written notice. The tenant may not end the lease during the first six months.'),
                ('h', '4. Pets'),
                ('p', 'Pets are allowed only with the written consent of the landlord. The tenant is responsible for any damage a pet causes.'),
                ('h', '5. Repairs'),
                ('p', 'The tenant pays for small repairs costing less than 150 euros each. The landlord pays for larger repairs and for the boiler, the roof and the windows.')]
    northwind = [[('h', f'Northwind Supplies, Invoice NW-1042 {NOTE}'),
                  ('p', 'Billed to Harbor Freight Hub, Dock Road 4, Cork. Invoice date 30 November 2026. Payment due by 30 December 2026.'),
                  ('t', INVOICE_NORTHWIND, [72, 250, 340, 450])]]
    price_pages = [[('h', f'Office Supplies Price List 2027 {NOTE}'), ('p', 'Prices are in euros, excluding VAT, valid from 1 January to 31 December 2027.'),
                    ('t', PRICE_LIST[:8], [72, 230, 300, 450])],
                   [('h', 'Price list, continued'), ('t', [PRICE_LIST[0]] + PRICE_LIST[8:], [72, 230, 300, 450])]]
    return [
        ('employee-handbook.md', _md('Employee Handbook',
            ('Annual leave', 'Every employee has 25 days of paid annual leave a year. Up to 5 unused days can be carried over, and must be used before 31 March of the next year.'),
            ('Sick leave', 'You can self-certify up to 3 days of sickness. From the fourth day a doctor\'s note is needed.'),
            ('Parental leave', 'Parents receive 16 weeks of parental leave on full pay, which can start up to two weeks before the expected birth.'),
            ('Remote work', 'Staff may work from home up to three days a week. Core hours, when everyone should be reachable, are from 10:00 to 16:00.'))),
        ('expense-policy.md', _md('Expense Policy',
            ('Mileage', 'Business travel in your own car is reimbursed at 0.45 euros per kilometre.'),
            ('Receipts', 'Submit receipts within 30 days of the expense. Claims without a receipt are not reimbursed.'),
            ('Approval', 'Any single expense above 500 euros needs approval from a director before it is made.'),
            ('Client meals', 'Client dinners are reimbursed up to 75 euros per person, including drinks.'))),
        ('it-security-policy.md', _md('IT Security Policy',
            ('Passwords', 'Passwords must be at least 14 characters long. Multi-factor authentication is required for email and every company system.'),
            ('Devices', 'Company laptops must use full-disk encryption. USB storage devices are blocked on all company machines.'),
            ('Incidents', 'Report a suspected security incident to security@example.test within one hour of noticing it.'))),
        ('lease-agreement.pdf', _pdf_text([lease_p1, lease_p2])),
        ('vendor-agreement.docx', S.docx([('h1', f'Logistics Services Agreement with Brightline Logistics {NOTE}'),
            ('h2', 'Payment terms'), ('p', 'Invoices are payable within 45 days of the invoice date.'),
            ('h2', 'Liability'), ('p', 'The total liability of either party is capped at the fees paid in the twelve months before the claim.'),
            ('h2', 'Governing law'), ('p', 'This agreement is governed by the laws of Ireland.'),
            ('h2', 'Renewal'), ('p', 'The agreement renews automatically for one year unless either party gives 90 days notice before the end of the term.'),
            ('h2', 'Service level'), ('p', 'Brightline guarantees on-time delivery for 99.5 percent of shipments each month.')])),
        ('invoice-northwind-nw1042.pdf', _pdf_text(northwind)),
        ('invoice-contoso-778.csv', _csv(INVOICE_CONTOSO)),
        ('price-list-2027.pdf', _pdf_text(price_pages)),
        ('financial-statement-q3.xlsx', S.xlsx({'Income statement': STATEMENT})),
        ('meeting-notes-product-sync.md', _md('Product sync, 3 November 2026',
            ('Decisions', 'The public launch moves from 1 December to 12 January because the payment provider review is not finished. The advertising budget for the launch is 18,000 euros.'),
            ('Actions', 'Priya Natarajan writes the onboarding emails by 20 November. Tomas Berg books the launch venue.'),
            ('Risks', 'If the payment review slips again, the launch happens without paid plans.'))),
        ('product-spec-orbit.md', _md('Orbit 14 laptop, product specification',
            ('Battery', 'The battery lasts up to 14 hours of video playback. It charges to 80 percent in 45 minutes with the 65 watt USB-C charger.'),
            ('Build', 'The laptop weighs 1.2 kilograms and is made of recycled aluminium.'),
            ('Warranty', 'Every Orbit 14 has a two-year warranty, which can be extended to four years.'))),
        ('onboarding-guide.html', (f'<html><head><title>First week</title></head><body><h1>Your first week {NOTE}</h1>'
            '<h2>Day one</h2><p>Collect your badge from reception at 9:00. IT sets up your laptop at 10:30.</p>'
            '<h2>Your buddy</h2><p>Every new starter is paired with a buddy from another team for their first three months.</p>'
            '<h2>Payroll</h2><p>Salaries are paid on the 25th of each month. Send your bank details to payroll in your first week.</p></body></html>').encode()),
        ('support-playbook.md', _md('Customer Support Playbook',
            ('Refunds', 'Customers can ask for a full refund within 30 days of purchase, without giving a reason.'),
            ('Response times', 'Priority tickets get a first answer within 4 business hours; normal tickets within 2 business days.'),
            ('Escalation', 'A ticket that is still open after 5 business days goes to the support lead.'))),
        ('board-minutes-october.docx', S.docx([('h1', f'Board minutes, 28 October 2026 {NOTE}'),
            ('p', 'The board approved hiring six engineers in the first quarter.'),
            ('p', 'The board agreed to move the head office to Lisbon in the second quarter of 2027.'),
            ('p', 'The next board meeting is on 27 January 2027.')])),
        ('home-insurance.md', _md('Home insurance policy summary',
            ('Excess', 'You pay the first 500 euros of every claim (the excess).'),
            ('Covered', 'The policy covers fire, theft and water damage from burst pipes.'),
            ('Not covered', 'Flooding from rivers or the sea is not covered, nor is wear and tear.'))),
        ('okrs-q1-2027.md', _md('Company objectives, first quarter 2027',
            ('Customers', 'Raise the net promoter score from 32 to 40.'),
            ('Growth', 'Reach 2,500 paying customers by the end of March.'),
            ('Team', 'Keep voluntary staff turnover below 8 percent.'))),
        ('release-notes-4-2.md', _md('Release notes, version 4.2',
            ('New', 'Dark mode for every screen. Reports can be exported to CSV.'),
            ('Fixed', 'Calendar sync no longer creates duplicate events after a time-zone change.'))),
        ('travel-policy.md', S.MARKDOWN),
        ('quarterly-report-draft.md', _md('Quarterly report draft',
            ('Revenue', 'The total revenue for the quarter was 1,284,000 euros.'))),
        ('quarterly-report-final.md', _md('Quarterly report final',
            ('Revenue', 'The total revenue for the quarter was 1,312,000 euros.'))),
        ('contract-v1.pdf', S.pdf(S.CONTRACT_V1)),
        ('contract-v2.pdf', S.pdf(S.CONTRACT_V2)),
    ]


# Questions and where their answer is: (question, the document, words the cited passage must contain). Worded differently from the documents on purpose.
QUESTIONS = [
    ('How many paid holidays do employees get each year?', 'employee-handbook.md', '25 days'),
    ('Until when can unused holiday be used?', 'employee-handbook.md', '31 March'),
    ('When do I need a doctor\'s note for being ill?', 'employee-handbook.md', 'fourth day'),
    ('How long is parental leave and is it paid?', 'employee-handbook.md', '16 weeks'),
    ('How many days can I work from home?', 'employee-handbook.md', 'three days a week'),
    ('What is the reimbursement rate for driving my own car?', 'expense-policy.md', '0.45'),
    ('Deadline for handing in receipts', 'expense-policy.md', '30 days'),
    ('Who has to sign off a large purchase?', 'expense-policy.md', 'director'),
    ('How much can I spend per person on a client dinner?', 'expense-policy.md', '75 euros'),
    ('Minimum password length', 'it-security-policy.md', '14 characters'),
    ('Can I use a USB stick on my work laptop?', 'it-security-policy.md', 'USB storage'),
    ('How quickly must a security breach be reported?', 'it-security-policy.md', 'one hour'),
    ('What is the monthly rent for the flat?', 'lease-agreement.pdf', '1,350 euros'),
    ('How much is the deposit?', 'lease-agreement.pdf', 'two months'),
    ('How much notice is needed to move out?', 'lease-agreement.pdf', 'sixty days'),
    ('Can the tenant keep a dog?', 'lease-agreement.pdf', 'written consent'),
    ('Who pays to fix the boiler?', 'lease-agreement.pdf', 'boiler'),
    ('When do we have to pay Brightline invoices?', 'vendor-agreement.docx', '45 days'),
    ('Which country\'s law applies to the logistics contract?', 'vendor-agreement.docx', 'Ireland'),
    ('How do we stop the logistics contract from renewing?', 'vendor-agreement.docx', '90 days'),
    ('What on-time delivery rate does the logistics supplier promise?', 'vendor-agreement.docx', '99.5'),
    ('What is the total due on the Northwind invoice?', 'invoice-northwind-nw1042.pdf', '3,210.30'),
    ('When is the Northwind invoice due?', 'invoice-northwind-nw1042.pdf', '30 December 2026'),
    ('How many hours of data migration did Contoso bill?', 'invoice-contoso-778.csv', 'Data migration'),
    ('What does a standing desk cost in 2027?', 'price-list-2027.pdf', '499.00'),
    ('Price of black toner', 'price-list-2027.pdf', '68.00'),
    ('What was net income in the third quarter?', 'financial-statement-q3.xlsx', '212400'),
    ('Operating expenses Q3 2026', 'financial-statement-q3.xlsx', '498200'),
    ('Why was the launch postponed?', 'meeting-notes-product-sync.md', 'payment provider review'),
    ('Who is writing the onboarding emails?', 'meeting-notes-product-sync.md', 'Priya'),
    ('How long does the Orbit laptop battery last?', 'product-spec-orbit.md', '14 hours'),
    ('How heavy is the Orbit 14?', 'product-spec-orbit.md', '1.2 kilograms'),
    ('Where do I get my access badge on the first day?', 'onboarding-guide.html', 'reception'),
    ('On which day of the month are salaries paid?', 'onboarding-guide.html', '25th'),
    ('Can a customer get their money back, and for how long?', 'support-playbook.md', '30 days'),
    ('How fast must we answer a priority ticket?', 'support-playbook.md', '4 business hours'),
    ('How many engineers did the board approve?', 'board-minutes-october.docx', 'six engineers'),
    ('Where is the head office moving?', 'board-minutes-october.docx', 'Lisbon'),
    ('Is river flooding covered by the home insurance?', 'home-insurance.md', 'not covered'),
    ('What is the target for the net promoter score?', 'okrs-q1-2027.md', '40'),
    ('What bug about duplicate events was fixed?', 'release-notes-4-2.md', 'duplicate events'),
    ('Hotel limit in London', 'travel-policy.md', '260'),
]
# Tables with every cell known (#33). Cell accuracy: a cell counts when the parsed table has the same text (spacing ignored) at the same row and column.
TABLES = [('invoice-northwind-nw1042.pdf', INVOICE_NORTHWIND), ('invoice-contoso-778.csv', INVOICE_CONTOSO), ('price-list-2027.pdf', PRICE_LIST),
          ('financial-statement-q3.xlsx', [[str(c) for c in r] for r in STATEMENT])]
# Planted conflicts (#45): a search whose results come from two documents that disagree about the same fact.
CONFLICTS = [('total revenue for the quarter', ('quarterly-report-draft.md', 'quarterly-report-final.md'))]
# Planted unsupported claims (#47): (claim, the document whose passage it cites, words that find that passage, supported?)
CLAIMS = [('The monthly rent is 1,350 euros.', 'lease-agreement.pdf', 'monthly rent', True),
          ('The monthly rent is 1,500 euros.', 'lease-agreement.pdf', 'monthly rent', False),
          ('Employees get 30 days of paid annual leave.', 'employee-handbook.md', 'paid annual leave', False),
          ('Invoices are payable within 45 days of the invoice date.', 'vendor-agreement.docx', 'payable within', True),
          ('The board approved hiring ten engineers.', 'board-minutes-october.docx', 'hiring engineers', False),
          ('The deposit is returned within 90 days.', 'lease-agreement.pdf', 'security deposit', False)]


# ------------------------------------------------------------------------------------------------------------------------------------------------ running
def _norm(text) -> str:
    return re.sub(r'\s+', ' ', str(text or '')).strip().lower()


def _hit(result, names, document, words) -> bool:
    return result.get('source_id') == names.get(document) and _norm(words) in _norm(result.get('text'))


def run(service, principal, add, wait=lambda: None, *, documents=None) -> dict:
    """Put the corpus in, then measure. -> the report (numbers and the ids of what missed; never document text beyond the question)."""
    names = {}
    for name, data in (documents or corpus()):
        names[name] = add(name, data)
    wait()
    sources = {s['id']: s for s in service.sources(principal)['sources']}
    not_ready = [n for n, sid in names.items() if sources.get(sid, {}).get('state') != 'ready']

    # retrieval and citation (#36, #37)
    at5 = at10 = cited = cites = top1 = 0
    misses, times = [], []
    for question, document, words in QUESTIONS:
        started = time.monotonic()
        found = service.search(principal, question, limit=10)['results']
        times.append((time.monotonic() - started) * 1000)
        ranks = [i for i, r in enumerate(found) if _hit(r, names, document, words)]
        at5 += bool(ranks and ranks[0] < 5)
        at10 += bool(ranks)
        if not ranks or ranks[0] >= 5:
            misses.append({'question': question, 'rank': ranks[0] + 1 if ranks else None})
        top1 += bool(ranks and ranks[0] == 0)
        if ranks:                                  # the right passage, wherever it ranked: does its citation open the same source at the same page?
            hit = found[ranks[0]]
            again = service.passage(principal, hit['passage_id'])
            cited += again['source_id'] == hit['source_id'] and again.get('page') == hit.get('page') and hit['open'] == f"/knowledge/{hit['source_id']}?passage={hit['passage_id']}"
            cites += 1
    n = len(QUESTIONS)

    # tables (#33)
    cells = correct = 0
    by_document = {}
    for document, expected in TABLES:
        blocks = [b for b in service.document(principal, names[document])['blocks'] if b.get('kind') == 'table']
        parsed = [row for b in blocks for i, row in enumerate(b.get('rows') or []) if not (i == 0 and parsed_header_seen(blocks, b))]
        rows = _align(expected, parsed)
        here = sum(1 for r, row in enumerate(expected) for c, cell in enumerate(row) if cell != '')
        good = sum(1 for r, row in enumerate(expected) for c, cell in enumerate(row) if cell != '' and r < len(rows) and c < len(rows[r]) and _norm(rows[r][c]) == _norm(cell))
        cells, correct = cells + here, correct + good
        by_document[document] = round(good / here, 3) if here else None

    # comparison (#35)
    changes = service.compare(principal, names['contract-v1.pdf'], names['contract-v2.pdf'])['changes']
    number = any(c.get('change') == 'changed' and c.get('numbers_changed') == ['1200', '1450'] for c in changes)
    notice = any(c.get('change') == 'changed' and 'sixty' in _norm(c.get('second', {}).get('text') or c.get('after') or '') for c in changes) or \
        any(c.get('change') == 'changed' and c.get('section', '').startswith('1.') for c in changes)
    moved = any(c.get('change') == 'moved' for c in changes)

    # planted conflicts (#45)
    reported = 0
    for query, (first, second) in CONFLICTS:
        found = service.search(principal, query, limit=10)
        reported += any({c['a']['source'], c['b']['source']} == {first, second} for c in found.get('possible_conflicts') or [])

    # planted unsupported claims (#47)
    flagged = kept = wrongly = 0
    for claim, document, words, supported in CLAIMS:
        hits = [r for r in service.search(principal, words, sources=[names[document]], limit=3)['results']]
        if not hits:
            wrongly += 1
            continue
        status = service.verify(principal, [{'claim': claim, 'passage_id': hits[0]['passage_id']}])['claims'][0]['status']
        if supported:
            kept += status == 'supported'
            wrongly += status != 'supported'
        else:
            flagged += status != 'supported'
            wrongly += status == 'supported'
    planted_false = sum(1 for c in CLAIMS if not c[3])

    return {'documents': len(names), 'not_ready': not_ready,
            'retrieval': {'questions': n, 'recall_at_5': round(at5 / n, 3), 'recall_at_10': round(at10 / n, 3), 'top_1': round(top1 / n, 3),
                          'citation_correct': round(cited / cites, 3) if cites else None, 'misses': misses},
            'tables': {'cells': cells, 'correct': correct, 'accuracy': round(correct / cells, 3) if cells else None, 'by_document': by_document},
            'comparison': {'changed_number': number, 'changed_notice': notice, 'moved_clause': moved},
            'conflicts': {'planted': len(CONFLICTS), 'reported': reported},
            'claims': {'planted_unsupported': planted_false, 'flagged': flagged, 'supported_kept': kept, 'wrong': wrongly},
            'search_ms': {'median': round(statistics.median(times), 1), 'p90': round(sorted(times)[int(0.9 * (len(times) - 1))], 1), 'max': round(max(times), 1)}}


def parsed_header_seen(blocks, block) -> bool:
    """A table that continues on the next page repeats its header row: count that row once (on the first part only)."""
    first = next((b for b in blocks if b.get('rows')), None)
    return block is not first and bool(block.get('rows')) and bool(first.get('rows')) and _norm(block['rows'][0]) == _norm(first['rows'][0])


def _align(expected, parsed):
    """The parsed rows in the expected order: each expected row is matched to the parsed row that shares its first cell (or, for a row without one, the next unused row)."""
    out, used = [], set()
    for row in expected:
        key = _norm(row[0])
        match = next((i for i, p in enumerate(parsed) if i not in used and p and _norm(p[0]) == key), None)
        if match is None:
            match = next((i for i in range(len(parsed)) if i not in used), None)
        if match is None:
            out.append([])
            continue
        used.add(match)
        out.append(parsed[match])
    return out
