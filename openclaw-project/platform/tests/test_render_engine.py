"""The conversion engine's own logic (the parts that need no external converter). The office, page and document converters only exist inside the
renderer image, so those routes are exercised there (deploy/renderer/README.md), not here. Skipped where openpyxl or Pillow are not installed."""
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

from agentai_platform.render import engine

HAVE = all(importlib.util.find_spec(name) for name in ('openpyxl', 'PIL'))


class RouteChecks(unittest.TestCase):
    def test_unknown_routes_are_refused_with_a_plain_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'song.mp3'; source.write_bytes(b'ID3')
            for target in ('pdf', 'xlsx', 'pptx', 'docx'):
                with self.assertRaises(engine.Failed) as caught:
                    engine.convert(source, target, Path(tmp))
                self.assertIn('cannot be turned into', str(caught.exception))
                self.assertNotIn(tmp, str(caught.exception))                     # never a path

    def test_numbers_become_numbers_and_identifiers_stay_text(self):
        self.assertEqual([engine.typed(v) for v in ('12', '-3.50', '007', '1e5', '2026-01-02', ' 4 ', '0', '0.5', '12345678901234567890', '')],
                         [12, -3.5, '007', '1e5', '2026-01-02', 4, 0, 0.5, '12345678901234567890', ''])


@unittest.skipUnless(HAVE, 'openpyxl and Pillow are only needed inside the renderer image')
class SheetAndImageChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_a_csv_becomes_a_real_workbook_and_a_formula_in_data_stays_text(self):
        from openpyxl import load_workbook
        source = self.dir / 'Q3 sales.csv'
        source.write_text('Month;Revenue;Code\nJan;1200;007\nFeb;1350.5;=1+1\n', encoding='utf-8')
        book = load_workbook(engine.convert(source, 'xlsx', self.dir))
        sheet = book.active
        self.assertEqual(sheet.title, 'Q3 sales')
        self.assertEqual([[c.value for c in row] for row in sheet.iter_rows()], [['Month', 'Revenue', 'Code'], ['Jan', 1200, '007'], ['Feb', 1350.5, '=1+1']])
        self.assertEqual(sheet['C3'].data_type, 's')                                 # not calculated
        self.assertTrue(sheet['A1'].font.bold); self.assertEqual(sheet.freeze_panes, 'A2')

    def test_a_sheet_description_gives_several_sheets_formats_and_formulas(self):
        from openpyxl import load_workbook
        source = self.dir / 'book.json'
        source.write_text(json.dumps({'sheets': [
            {'name': 'Sales', 'columns': ['Month', 'Revenue'], 'rows': [['Jan', 1200], ['Feb', 1300], ['Total', '=SUM(B2:B3)']], 'formats': {'B': '#,##0.00'}, 'widths': [20, 15]},
            {'name': 'Notes', 'rows': [['plain'], [None], [True]]}]}))
        book = load_workbook(engine.convert(source, 'xlsx', self.dir))
        self.assertEqual(book.sheetnames, ['Sales', 'Notes'])
        self.assertEqual(book['Sales']['B4'].value, '=SUM(B2:B3)'); self.assertEqual(book['Sales']['B4'].data_type, 'f')
        self.assertEqual(book['Sales']['B2'].number_format, '#,##0.00'); self.assertEqual(book['Sales'].column_dimensions['A'].width, 20)
        records = self.dir / 'people.json'
        records.write_text(json.dumps([{'Name': 'Ada', 'Age': 36}, {'Name': 'Lin', 'City': 'Oslo'}]))
        rows = [[c.value for c in row] for row in load_workbook(engine.convert(records, 'xlsx', self.dir)).active.iter_rows()]
        self.assertEqual(rows, [['Name', 'Age', 'City'], ['Ada', 36, None], ['Lin', None, 'Oslo']])
        for bad in ('not json', '{"sheets": []}', '{"sheets": [{"rows": "x"}]}', '{"sheets": [{"rows": ["x"]}]}'):
            source.write_text(bad)
            with self.assertRaises(engine.Failed):
                engine.convert(source, 'xlsx', self.dir)

    def test_pictures_convert_between_formats_and_get_a_small_preview(self):
        from PIL import Image
        source = self.dir / 'logo.png'
        Image.new('RGBA', (3000, 2000), (200, 30, 30, 128)).save(source)
        for target, magic in (('jpg', b'\xff\xd8\xff'), ('webp', b'RIFF'), ('gif', b'GIF8'), ('pdf', b'%PDF')):
            self.assertTrue(engine.convert(source, target, self.dir).read_bytes().startswith(magic), target)
        shot = engine.preview(source, self.dir)
        with Image.open(shot) as small:
            self.assertEqual(small.format, 'JPEG'); self.assertLessEqual(max(small.size), 1400)
        self.assertIsNone(engine.preview(self.dir / 'notes.txt', self.dir))
        broken = self.dir / 'broken.png'; broken.write_bytes(b'not a picture')
        with self.assertRaises(engine.Failed):
            engine.convert(broken, 'jpg', self.dir)


if __name__ == '__main__':
    unittest.main()
