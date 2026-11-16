"""File organization (roadmap #30): the content scan, uploads of the launch formats, files with the same content, and one catalogue with folders."""
import io
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from agentai_platform import content_scan, files
from agentai_platform.catalogue import Catalogue, family
from agentai_platform.content_scan import Refused
from agentai_platform.files import FileService, Rejected
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound, Principal
from agentai_platform.storage import RootStore
from agentai_platform.store import Store

MAIN = content_scan.OFFICE_MAIN
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + (64).to_bytes(4, 'big') + (48).to_bytes(4, 'big') + b'\x08\x02\x00\x00\x00' + b'\x00' * 20
PDF = b'%PDF-1.7\n1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n2 0 obj<< /Type /Pages /Count 0 >>endobj\ntrailer<< /Root 1 0 R >>\n%%EOF'


def office(kind='docx', *, extra=None, types=None, rels=None, encrypted=False):
    """A minimal, well-formed modern Office package, with whatever a test adds to it."""
    part = {'docx': 'word/document.xml', 'xlsx': 'xl/workbook.xml', 'pptx': 'ppt/presentation.xml'}[kind]
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', types or f'<Types><Override PartName="/{part}" ContentType="{MAIN[kind]}"/></Types>')
        z.writestr('_rels/.rels', rels or '<Relationships><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="' + part + '"/></Relationships>')
        z.writestr(part, '<document><body>Quarterly numbers</body></document>')
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    data = out.getvalue()
    if encrypted:
        data = data.replace(b'PK\x03\x04\x14\x00\x00\x00', b'PK\x03\x04\x14\x00\x01\x00', 1).replace(b'PK\x01\x02\x14\x03\x14\x00\x00\x00', b'PK\x01\x02\x14\x03\x14\x00\x01\x00', 1)
    return data


class Scan(unittest.TestCase):
    def refused(self, kind, data, word):
        with self.assertRaises(Refused) as caught:
            content_scan.scan(kind, data)
        self.assertIn(word, str(caught.exception))

    def test_ordinary_files_of_every_launch_format_pass(self):
        for kind in ('docx', 'xlsx', 'pptx'):
            content_scan.scan(kind, office(kind))
            self.assertEqual(content_scan.office_kind(office(kind)), kind)
        content_scan.scan('pdf', PDF); content_scan.scan('png', PNG); content_scan.scan('text', b'hello'); content_scan.scan('json', b'{}')
        link = '<Relationships><Relationship Id="r9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com" TargetMode="External"/></Relationships>'
        content_scan.scan('docx', office(extra={'word/_rels/document.xml.rels': link}))          # a plain link in the text is not a remote object

    def test_office_files_with_macros_programs_or_remote_objects_are_refused(self):
        self.refused('docx', office(extra={'word/vbaProject.bin': b'x'}), 'macros or a program')
        self.refused('xlsx', office('xlsx', extra={'xl/activeX/activeX1.xml': b'x'}), 'macros or a program')
        self.refused('docx', office(extra={'word/embeddings/oleObject1.bin': b'x'}), 'embedded')
        self.refused('docx', office(types=f'<Types><Override ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/><Override ContentType="{MAIN["docx"]}"/></Types>'), 'macros')
        template = '<Relationships><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" Target="https://evil.test/t.dotm" TargetMode="External"/></Relationships>'
        self.refused('docx', office(extra={'word/_rels/settings.xml.rels': template}), 'loads something from elsewhere')
        self.refused('docx', office('xlsx'), 'not the kind of document its name says')
        self.refused('docx', b'PK\x03\x04 not a zip at all', 'damaged')

    def test_packages_built_to_exhaust_memory_and_protected_files_are_refused(self):
        self.refused('docx', office(extra={'word/media/big.bin': b'\x00' * 30_000_000}), 'expands to far more')
        self.refused('docx', office(extra={f'word/p{n}.xml': b'' for n in range(5001)}), 'too many parts')
        self.refused('docx', office(encrypted=True), 'password-protected')
        self.assertIsNone(content_scan.office_kind(b'PK\x03\x04' + b'\x00' * 40))

    def test_pdfs_with_scripts_actions_embedded_files_or_encryption_are_refused_however_they_are_hidden(self):
        self.refused('pdf', PDF.replace(b'/Type /Catalog', b'/Type /Catalog /OpenAction << /S /JavaScript /JS (app.alert(1)) >>'), 'a script')
        self.refused('pdf', PDF.replace(b'/Type /Catalog', b'/Type /Catalog /OpenAction << /S /J#61vaScript >>'), 'a script')          # a name written with an escape
        self.refused('pdf', PDF + b'\n3 0 obj<< /S /Launch /F (cmd.exe) >>endobj', 'starts a program')
        self.refused('pdf', PDF + b'\n3 0 obj<< /Type /EmbeddedFile >>endobj', 'embedded inside')
        self.refused('pdf', PDF + b'\n3 0 obj<< /Encrypt 4 0 R >>endobj', 'encryption')
        hidden = zlib.compress(b'4 0 obj << /S /JavaScript /JS (x) >> endobj')
        self.refused('pdf', PDF + b'\n3 0 obj<< /Type /ObjStm /Filter /FlateDecode /Length ' + str(len(hidden)).encode() + b' >>\nstream\n' + hidden + b'\nendstream endobj', 'a script')
        content_scan.scan('pdf', PDF + b'\n3 0 obj<< /Title (About the /JSON format and /Launching a product) >>endobj')       # a longer word that only starts the same is not a hit

    def test_a_picture_that_would_exhaust_memory_and_anything_unknown_are_refused(self):
        huge = PNG[:16] + (40000).to_bytes(4, 'big') + (40000).to_bytes(4, 'big') + PNG[24:]
        self.refused('png', huge, 'too large')
        self.refused('archive', b'PK\x03\x04', 'not accepted')
        self.refused('binary', b'\x00\x01', 'not accepted')

    def test_a_scanning_engine_on_the_host_can_refuse_and_fails_closed(self):
        self.assertIsNone(content_scan.scan('text', b'fine', engine=lambda data: None))
        with self.assertRaises(Refused):
            content_scan.scan('text', b'bad', engine=lambda data: 'Eicar-Test-Signature')
        with self.assertRaises(Refused) as caught:
            content_scan.scan('text', b'x', engine=lambda data: 1 / 0)
        self.assertIn('could not be checked', str(caught.exception))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 's' / 'db.sqlite3'); self.store.initialize(); self.now = 2000000000
        with self.store.connect() as con:
            for a in ('a', 'b'):
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (a,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (a, 'actor-' + a))
                for p in ('p1', 'p2'):
                    con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (a, p + a, 'Project ' + p))
        root = Path(self.tmp.name) / 'files'; root.mkdir(mode=0o700)
        self.storage = RootStore(str(root))
        self.files = FileService(self.store, storage=self.storage, clock=lambda: self.now)
        self.catalogue = Catalogue(self.store, clock=lambda: self.now)
        self.a, self.b = Principal('a', 'actor-a', 'customer'), Principal('b', 'actor-b', 'customer')

    def up(self, name, data, who=None, project='p1', folder=None):
        who = who or self.a
        return self.files.upload(who, project + who.account_id, [(name, '', data)], folder_id=folder)

    def rows(self, sql, args=()):
        with self.store.connect() as con:
            return [dict(r) for r in con.execute(sql, args).fetchall()]

    def blobs(self):
        return sorted(p.name for p in Path(self.tmp.name, 'files').rglob('*') if p.is_file())


class Uploads(Base):
    def test_the_launch_formats_are_accepted_by_content_not_by_name(self):
        for name, data, media in (('report.docx', office(), files.MEDIA['docx']), ('numbers.xlsx', office('xlsx'), files.MEDIA['xlsx']), ('talk.pptx', office('pptx'), files.MEDIA['pptx']),
                                  ('scan.pdf', PDF, 'application/pdf'), ('photo.png', PNG, 'image/png'), ('notes.md', b'# Notes', 'text/markdown'), ('data.csv', b'a,b\n1,2', 'text/csv'),
                                  ('mail.eml', b'From: a@b.test\nSubject: Hi\n\nBody', 'message/rfc822'), ('config.json', b'{"a": 1}', 'application/json')):
            got = self.up(name, data)
            self.assertEqual((got['rejected'], got['accepted'][0]['media_type']), ([], media), name)
        for name, data, reason in (('report.docx', office('xlsx'), 'does not match'), ('report.docx', b'plain text', 'does not match'), ('old.doc', b'\xd0\xcf\x11\xe0', 'allowlist'),
                                   ('bundle.zip', b'PK\x03\x04', 'allowlist'), ('macro.docx', office(extra={'word/vbaProject.bin': b'x'}), 'macros'), ('bad.json', b'{nope', 'invalid JSON'),
                                   ('script.pdf', PDF + b' /JavaScript ', 'script'), ('run.exe', b'MZ\x90\x00', 'allowlist')):
            with self.assertRaises(Rejected) as caught:
                self.up(name, data)
            self.assertIn(reason, str(caught.exception), name)
        self.assertEqual(len(self.blobs()), 9)                           # nothing that was refused was ever written

    def test_one_refused_file_does_not_refuse_the_others(self):
        got = self.files.upload(self.a, 'p1a', [('good.txt', '', b'fine'), ('macro.docx', '', office(extra={'word/vbaProject.bin': b'x'}))])
        self.assertEqual(([f['name'] for f in got['accepted']], [r['name'] for r in got['rejected']]), (['good.txt'], ['macro.docx']))

    def test_the_same_content_is_linked_and_never_stored_twice(self):
        first = self.up('report.docx', office())['accepted'][0]
        again = self.up('report copy.docx', office())['accepted'][0]
        self.assertEqual((again['id'], again['already_here']), (first['id'], True))                      # the same place: nothing new at all
        elsewhere = self.up('report.docx', office(), project='p2')['accepted'][0]
        self.assertEqual((elsewhere['same_as'], elsewhere['id'] != first['id']), (first['id'], True))    # another project: its own entry, the same bytes
        self.assertEqual(len(self.blobs()), 1)
        self.assertEqual(self.rows('SELECT count(*) AS n FROM project_files')[0]['n'], 2)
        theirs = self.up('report.docx', office(), who=self.b)['accepted'][0]
        self.assertNotIn('same_as', theirs)                                                              # another account never learns the content exists
        self.assertEqual(len(self.blobs()), 2)
        self.assertEqual(self.files.delete_upload(self.a, first['id'])['bytes_removed'], False)          # the other entry still uses the bytes
        self.assertEqual(len(self.blobs()), 2)
        self.assertEqual(self.files.delete_upload(self.a, elsewhere['id'])['bytes_removed'], True)
        self.assertEqual(len(self.blobs()), 1)
        with self.assertRaises(NotFound):
            self.files.delete_upload(self.b, first['id'])


class Organizing(Base):
    def setUp(self):
        super().setUp()
        self.doc = self.up('report.docx', office())['accepted'][0]['id']
        self.pic = self.up('photo.png', PNG)['accepted'][0]['id']
        with self.store.connect() as con:
            con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES ('a','d1',1,'ready')")
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('a','p1a','c1','d1')")
            con.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES ('a','p1a','c1','t1','completed',0)")
            for version in (1, 2):
                con.execute("""INSERT INTO artifacts(account_id,project_id,task_id,id,version,display_name,media_type,size_bytes,sha256,storage_ref,created_at)
                    VALUES ('a','p1a','t1','art1',?,'summary.pdf','application/pdf',10,?,?,?)""", (version, str(version) * 64, f'artifacts/art1/{version}', f'2033-05-1{version}T00:00:00.000Z'))

    def names(self, **filters):
        return [f['name'] for f in self.catalogue.entries(self.a, **filters)['files']]

    def test_uploads_and_made_files_are_one_list_with_filters(self):
        every = self.catalogue.entries(self.a)
        self.assertEqual(sorted((f['name'], f['source'], f['family']) for f in every['files']),
                         [('photo.png', 'uploaded', 'picture'), ('report.docx', 'uploaded', 'document'), ('summary.pdf', 'made', 'document')])
        made = next(f for f in every['files'] if f['kind'] == 'made')
        self.assertEqual((made['version'], made['versions']), (2, 2))                                    # one entry for a made file, its newest version
        self.assertEqual(self.names(source='made'), ['summary.pdf'])
        self.assertEqual(self.names(kind='picture'), ['photo.png'])
        self.assertEqual(self.names(query='REPORT'), ['report.docx'])
        self.assertEqual(self.names(project_id='p2a'), [])
        self.assertEqual(self.catalogue.entries(self.b)['files'], [])
        copy = self.up('again.docx', office(), project='p2')['accepted'][0]['id']
        marked = {f['id']: f['copy_of'] for f in self.catalogue.entries(self.a)['files']}
        self.assertEqual((marked[self.doc], marked[copy]['id']), (None, self.doc))

    def test_folders_moving_and_renaming(self):
        reports = self.catalogue.create_folder(self.a, 'p1a', 'Reports')['id']
        q3 = self.catalogue.create_folder(self.a, 'p1a', 'Q3', reports)['id']
        self.catalogue.place(self.a, 'upload', self.doc, folder_id=q3, name='Q3 board report.docx')
        self.catalogue.place(self.a, 'made', 'art1', folder_id=reports)
        self.assertEqual(self.names(folder_id=q3), ['Q3 board report.docx'])
        self.assertEqual(self.names(folder_id=reports), ['summary.pdf'])
        self.assertEqual(self.names(folder_id=None), ['photo.png'])
        self.assertEqual({f['name']: f['files'] for f in self.catalogue.entries(self.a)['folders']}, {'Reports': 1, 'Q3': 1})
        self.assertEqual(self.rows("SELECT display_name FROM project_files WHERE id=?", (self.doc,))[0]['display_name'], 'report.docx')      # the file itself is not rewritten
        self.catalogue.place(self.a, 'upload', self.doc, name=None)                                      # its own name again, still in its folder
        self.assertEqual(self.names(folder_id=q3), ['report.docx'])
        self.catalogue.change_folder(self.a, q3, name='Third quarter')
        with self.assertRaises(Conflict):
            self.catalogue.create_folder(self.a, 'p1a', 'reports')                                       # the same name in another letter case
        with self.assertRaises(Conflict):
            self.catalogue.change_folder(self.a, reports, parent_id=q3)                                  # never into its own subfolder
        with self.assertRaises(ValueError):
            self.catalogue.create_folder(self.a, 'p1a', 'a/b')
        gone = self.catalogue.delete_folder(self.a, reports)                                             # nothing inside is deleted: it moves up
        self.assertEqual(gone['files_moved_up'], 1)
        self.assertEqual(sorted(self.names(folder_id=None)), ['photo.png', 'summary.pdf'])
        self.assertEqual([(f['name'], f['parent_id']) for f in self.catalogue.entries(self.a)['folders']], [('Third quarter', None)])
        self.assertEqual(self.names(folder_id=q3), ['report.docx'])

    def test_a_folder_belongs_to_its_project_and_its_account(self):
        other = self.catalogue.create_folder(self.a, 'p2a', 'Elsewhere')['id']
        mine = self.catalogue.create_folder(self.a, 'p1a', 'Mine')['id']
        theirs = self.catalogue.create_folder(self.b, 'p1b', 'Theirs')['id']
        for call in (lambda: self.catalogue.place(self.a, 'upload', self.doc, folder_id=other), lambda: self.catalogue.place(self.a, 'upload', self.doc, folder_id=theirs),
                     lambda: self.catalogue.place(self.b, 'upload', self.doc, folder_id=theirs), lambda: self.catalogue.change_folder(self.b, mine, name='x'),
                     lambda: self.catalogue.delete_folder(self.b, mine), lambda: self.catalogue.create_folder(self.a, 'p1b', 'x'), lambda: self.catalogue.create_folder(self.a, 'p1a', 'x', theirs),
                     lambda: self.up('x.txt', b'x', folder=other), lambda: self.catalogue.place(self.a, 'made', 'nope', folder_id=mine)):
            with self.assertRaises(NotFound):
                call()
        self.assertEqual(self.up('in.txt', b'into a folder', folder=mine)['accepted'][0]['name'], 'in.txt')
        self.assertEqual(self.names(folder_id=mine), ['in.txt'])
        self.assertEqual([f['name'] for f in self.catalogue.entries(self.b)['folders']], ['Theirs'])

    def test_what_sort_of_thing_a_file_is(self):
        self.assertEqual([family(m, n) for m, n in (('image/png', 'a.png'), (files.MEDIA['xlsx'], 'a.xlsx'), ('text/csv', 'a.csv'), (files.MEDIA['pptx'], 'a.pptx'), ('application/pdf', 'a.pdf'),
                                                    ('application/json', 'a.json'), ('text/plain', 'a.txt'), ('message/rfc822', 'a.eml'), ('application/zip', 'a.zip'))],
                         ['picture', 'spreadsheet', 'spreadsheet', 'slides', 'document', 'data', 'text', 'text', 'other'])


if __name__ == '__main__':
    unittest.main()
