"""The assistant's file tool: hand the customer a file, in the format they asked for.

The assistant writes its work in its own workspace (it has the runtime's write tools). `lumina_file_deliver` takes one of those files and makes it a
download for the customer, optionally converting it first: Markdown or HTML to PDF or Word, a table to Excel, an outline to PowerPoint, several files to
a ZIP, one office or image format to another. Conversions run in the render service (render/), never in this process.

The file's content never passes through the model call: the tool is given a path, and the bytes are read from the account's own workspace through the
cell bridge, so a document can be far larger than a tool argument. The assistant gets back a picture of the first page to check before it answers.

Rules that hold whatever the assistant sends:
  - only files inside the calling account's own workspace are read (the bridge resolves the cell from the account, never from the call);
  - a native program or installer is never delivered;
  - the file is stored under the task that made the call, in that task's own project;
  - storage limits apply as for every other file.
"""
from __future__ import annotations
import base64
import copy
import io
import zipfile

from .adapters import CapabilityUnavailable
from .artifacts import NAME_LIMIT, base_name, media_for, safe_name
from .lifecycle.types import Conflict
from .lifecycle.workspace import MAX_FILE_BYTES, is_program, safe_path
from .render.client import RenderRefused
from .render.engine import TARGETS

NAME = 'lumina_file_deliver'
FORMATS = (*TARGETS, 'zip')
MAX_INCLUDE = 20
MAX_TOTAL_BYTES = 60 * 1024 * 1024
PREVIEWABLE = {'pdf', 'docx', 'odt', 'rtf', 'doc', 'xlsx', 'xls', 'ods', 'pptx', 'ppt', 'odp', 'png', 'jpg', 'jpeg', 'webp', 'gif'}

TOOL = {'name': NAME, 'description': (
    'Give the customer a file. Call this whenever they ask for a file, a document, a download or a specific format (PDF, Word, Excel, PowerPoint, CSV, an image, a ZIP...). '
    'First write the content as a file in your workspace, then call this with its path. The customer gets a download under your answer and in Files. '
    'To deliver in another format, set "convert_to": write Markdown or HTML and convert to pdf or docx; write CSV, or a JSON sheet description, and convert to xlsx; '
    'write Markdown with one "# heading" per slide and convert to pptx; convert an SVG or HTML chart to png; convert between office formats; or pass several files and '
    'convert to zip. A JSON sheet description is {"sheets":[{"name":"Sales","columns":["Month","Revenue"],"rows":[["Jan",1200],["Total","=SUM(B2:B2)"]],'
    '"formats":{"B":"#,##0.00"}}]}; a cell starting with "=" is a formula there (in CSV it stays text). Files a document refers to (its images) go in "include". '
    'You get back a picture of the first page when there is one: look at it, and if the layout is wrong, fix your source and call again with the same name (that replaces '
    'the file with a new version). Never tell the customer a file is ready unless this tool said it was delivered. If it fails, say plainly what could not be made.'),
    'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['path'], 'properties': {
        'path': {'type': 'string', 'minLength': 1, 'maxLength': 240, 'description': 'The file in your workspace, relative to the workspace folder, for example "report.md" or "out/sales.csv".'},
        'convert_to': {'type': 'string', 'enum': list(FORMATS), 'description': 'Deliver in this format instead of the format of "path". Leave out to deliver the file as it is.'},
        'name': {'type': 'string', 'minLength': 1, 'maxLength': 120, 'description': 'The file name the customer sees, for example "Q3 report.pdf". Defaults to the name of "path" with the right ending.'},
        'include': {'type': 'array', 'maxItems': MAX_INCLUDE, 'items': {'type': 'string', 'minLength': 1, 'maxLength': 240},
                    'description': 'Other workspace files this one needs (images used by a document), or the other files to pack when converting to zip.'}}}}


def human(size: int) -> str:
    return f'{size} B' if size < 1024 else f'{size / 1024:.0f} KB' if size < 1048576 else f'{size / 1048576:.1f} MB'


class FileTools:
    """What `tool_relay.Relay` calls. Same shape as the other tools: `call(account, arguments, closed, *, name, request_id)` -> (text, is_error[, jpeg_b64])."""
    names = frozenset({NAME})

    def __init__(self, store, artifacts, *, gateway_for, renderer=None, events=None, enabled=lambda account: True):
        """artifacts: ArtifactService. gateway_for(account) -> NativeGateway. renderer: RenderRpc or None (then files are delivered as written, never converted)."""
        self.store, self.artifacts, self.gateway_for, self.renderer, self.events, self._enabled = store, artifacts, gateway_for, renderer, events, enabled

    def enabled(self, account):
        try:
            return self.artifacts is not None and bool(self._enabled(account))
        except Exception:
            return False

    @staticmethod
    def specs():
        return [copy.deepcopy(TOOL)]

    # ---- pieces ------------------------------------------------------------------------------------------------------------------------------

    def _read(self, gateway, path):
        info = gateway.workspace_stat(path)
        if 'size' not in info:
            raise ValueError(f'"{path}" cannot be delivered: {info.get("reason", "not found")}.')
        return gateway.workspace_read(path, info['size'])

    @staticmethod
    def _zip(files):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path, data in files.items():
                archive.writestr(path, data)
        return buffer.getvalue()

    def _project(self, account, request_id):
        with self.store.connect() as con:
            row = con.execute('''SELECT c.project_id FROM customer_requests r JOIN conversations c ON c.account_id=r.account_id AND c.id=r.conversation_id
                WHERE r.account_id=? AND r.id=?''', (account, request_id)).fetchone()
        return row['project_id'] if row else None

    @staticmethod
    def _shown_name(path, wanted, kind):
        """The name the customer sees: the one asked for, or the source's own path, always ending in the format actually delivered (`kind`)."""
        asked = wanted.strip() if isinstance(wanted, str) else ''
        if '/' in asked:
            raise ValueError('Give "name" as a file name, without folders.')
        name = asked or path
        if kind and not name.lower().endswith('.' + kind):
            last = base_name(name)
            known = '.' in last and len(last.rsplit('.', 1)[1]) <= 5 and last.rsplit('.', 1)[1].isalnum()      # "Q3 report.md" has an ending to replace; "Q3 v1.2 final report" does not
            name = (name.rsplit('.', 1)[0] if known else name) + '.' + kind
        try:
            return safe_name(name[:NAME_LIMIT])
        except ValueError:
            raise ValueError('That file name cannot be used. Use letters, numbers, spaces, dots and dashes.')

    # ---- the call ----------------------------------------------------------------------------------------------------------------------------

    def call(self, account, arguments, closed=lambda: False, *, name, request_id=None):
        try:
            if name != NAME or not self.enabled(account):
                return 'Delivering files is not available.', True
            if not request_id:
                return 'This call does not belong to a running task. Nothing was delivered.', True
            if not isinstance(arguments, dict) or not set(arguments) <= {'path', 'convert_to', 'name', 'include'}:
                raise ValueError('Give a "path", and optionally "convert_to", "name" and "include".')
            path, target, include = arguments.get('path'), arguments.get('convert_to'), arguments.get('include') or []
            if safe_path(path) is None:
                raise ValueError('Give "path" as a file inside your workspace, for example "report.md". Folders named tmp or scratch are never delivered.')
            if target is not None and target not in FORMATS:
                raise ValueError('"convert_to" must be one of: ' + ', '.join(FORMATS) + '.')
            if not isinstance(include, list) or len(include) > MAX_INCLUDE or any(safe_path(p) is None for p in include):
                raise ValueError('"include" must be a list of up to 20 files inside your workspace.')
            source_kind = path.rsplit('.', 1)[-1].lower() if '.' in base_name(path) else ''
            if target == source_kind or (target == 'jpg' and source_kind == 'jpeg'):
                target = None                                          # already in that format: deliver as written
            if include and target is None:
                raise ValueError('"include" is only used when converting. To give the customer several files, call this once per file, or convert to zip.')
            shown = self._shown_name(path, arguments.get('name'), target or source_kind)
            project = self._project(account, request_id)
            if project is None:
                return 'This call does not belong to a running task. Nothing was delivered.', True
            gateway = self.gateway_for(account)
            files = {}
            for item in dict.fromkeys([path, *include]):
                files[item] = self._read(gateway, item)
                if sum(len(d) for d in files.values()) > MAX_TOTAL_BYTES:
                    raise ValueError('These files are too large together (the limit is 60 MB).')
            if closed():
                return 'The connection closed; nothing was delivered.', True
            data, shot, pages = files[path], None, None
            if target == 'zip':
                data = self._zip(files)
            elif target is not None:
                if self.renderer is None:
                    return (f'Converting to .{target} is not available right now. Nothing was delivered. Deliver the file as it is (leave out "convert_to"), '
                            'or tell the customer this format cannot be made at the moment.'), True
                made = self.renderer.convert(path, target, files)
                data, shot, pages = made['data'], made['preview'], made['pages']
                if not data:
                    return 'The conversion produced nothing. Nothing was delivered.', True
            elif self.renderer is not None and source_kind in PREVIEWABLE and len(data) <= 20 * 1024 * 1024:
                try:
                    shot = self.renderer.convert(path, None, {path: data})['preview']
                except (RenderRefused, CapabilityUnavailable):
                    shot = None                                        # the picture is a courtesy; the file is delivered either way
            if len(data) > MAX_FILE_BYTES:
                return f'The file is {human(len(data))}; the limit for one file is 50 MB. Nothing was delivered.', True
            if is_program(shown, data[:8]):
                return 'Programs and installers are not delivered. Nothing was delivered.', True
            if closed():
                return 'The connection closed; nothing was delivered.', True
            saved = self.artifacts.capture_or_version(account_id=account, project_id=project, task_id=request_id, name=shown, media_type=media_for(shown), data=data)
            if saved is None:
                return f'"{shown}" is already delivered and has not changed. The customer has it under this conversation and in Files.', False
            if shot:
                self.artifacts.save_preview(account, saved['artifact_id'], saved['version'], shot)
            if self.events is not None:
                try:
                    self.events.append(account, request_id, 'artifact', {'artifact_id': saved['artifact_id'], 'version': saved['version'], 'name': shown, 'sha256': saved['sha256']}, 'agent')
                except Exception:
                    pass                                               # the timeline is a view; the file is already saved
            facts = ', '.join(x for x in (f'{pages} page{"" if pages == 1 else "s"}' if pages else '', human(len(data)),
                                          f'version {saved["version"]}' if saved['version'] > 1 else '') if x)
            text = (f'Delivered "{shown}" ({facts}). The customer can download it under your answer and in Files; do not paste its content into the chat. '
                    + ('The picture shows its first page: check it. If something is wrong, fix your source and call again with the same name.' if shot
                       else 'No preview is available for this format.'))
            return (text, False, base64.b64encode(shot).decode()) if shot else (text, False)
        except ValueError as error:
            return (str(error) or 'Invalid request.') + ' Nothing was delivered.', True
        except RenderRefused as error:
            return f'The file could not be converted: {error}. Nothing was delivered. Fix the source file, or deliver it in another format.', True
        except Conflict:
            return 'The customer\'s storage is full. Nothing was delivered. Tell them to delete files they no longer need in Files.', True
        except CapabilityUnavailable:
            return 'The file could not be read or converted right now. Nothing was delivered. Try once more; if it fails again, tell the customer.', True
        except Exception:
            return 'Something went wrong. Nothing was delivered.', True
