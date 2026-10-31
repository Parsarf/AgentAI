"""Small JSON-lines bridge to the macOS helper. No third-party packages."""
import json
import subprocess

from loop import Paused


class NativeError(RuntimeError):
    pass


class Controller:
    def __init__(self, binary):
        self.proc = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, bufsize=1)

    def call(self, command, **params):
        self.proc.stdin.write(json.dumps({'cmd': command, **params}) + '\n')
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise NativeError('Mac helper exited')
        reply = json.loads(line)
        if not reply.get('ok'):
            error = reply.get('error', 'Mac action failed')
            if reply.get('paused'):
                raise Paused(error)
            raise NativeError(error)
        return reply

    def shot(self):
        return self.call('shot')

    def act(self, plan, token):
        return self.call('act', plan=plan, token=token).get('result', 'input delivered; verify on next picture')

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc.stdin.close()
        self.proc.stdout.close()

