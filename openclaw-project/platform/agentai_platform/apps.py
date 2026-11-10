"""Executable deliveries are separate from the read-only generative UI registry."""

MAX_APP_BYTES = 512 * 1024
RUNTIMES = {'html', 'python', 'javascript'}


def application(value):
    if not isinstance(value, dict) or set(value) - {'version', 'title', 'runtime', 'code'}:
        raise ValueError('invalid application')
    if type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('invalid application version')
    if not isinstance(value.get('runtime'), str) or value['runtime'] not in RUNTIMES:
        raise ValueError('unsupported runtime')
    if not isinstance(value.get('title'), str) or not value['title'].strip() or not 1 <= len(value['title']) <= 120:
        raise ValueError('invalid title')
    code = value.get('code')
    if not isinstance(code, str) or not code.strip() or len(code.encode('utf-8')) > MAX_APP_BYTES:
        raise ValueError('invalid application source')
    return {k: value[k] for k in ('version', 'title', 'runtime', 'code')}


def delivery_prompt():
    return '''[Lumina app delivery]
When asked to build an app, program, game or tool, choose the delivery that lets the customer USE it in Lumina.
For small self-contained tools (calculator, converter, quiz, game), prefer an interactive HTML/CSS/JavaScript app in chat.
Emit a separate ```lumina-app fence containing exactly one JSON object:
{"version":1,"title":"Calculator","runtime":"html","code":"<!doctype html>...complete self-contained app..."}
This is executable application source, separate from read-only answer documents. Never nest it in a display block.
The player supports html, python and javascript. Save the runnable entry point as a workspace-root .html file (for example app.html); build/ and dist/ are not collected as downloads. HTML must bundle all CSS/JS and assets inline: no external scripts, imports, URLs, backend calls or relative files. Use accessible responsive controls and real working logic. A source example alone does not need an app fence.
If a particular language or source file is requested, honor that request AND provide a way to use it: standalone .html files open in the app player, .py files run in a browser Python console, and .js files run in a browser JavaScript console. Preserve source downloads. Python/JavaScript consoles accept newline-separated standard input supplied before Run; EOF follows the last line. Python supports its standard library; no native desktop UI, server processes, pip installation or system commands. JavaScript is browser JavaScript, not Node.
For larger applications, include the full source project plus a self-contained browser interface/build when feasible. Verify the actual runnable entry point. Never claim that a server, database, native desktop app or arbitrary language runtime is available in the browser player. If the requested stack needs such an environment, use an actually available isolated hosting tool and verify its preview; otherwise explain the concrete missing capability and deliver a usable browser version when possible. Do not say the app is ready to use based solely on running tests or writing a file.
Do not execute code examples automatically. The customer opens or runs the app explicitly.\n'''
