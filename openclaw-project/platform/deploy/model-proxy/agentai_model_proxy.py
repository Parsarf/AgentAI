#!/usr/bin/env python3
"""HTTP-aware relay: the only door from customer cells to the model proxy (10.77.0.1:4000 -> LiteLLM loopback).

A cell may ask the model for completions and list models, nothing else. Every other LiteLLM route (key, user, team and spend
management, config, health detail) is refused here, so a customer's key can never read another customer's usage or mint new
keys even if LiteLLM would allow it. LiteLLM still authenticates every request with the cell's own virtual key (own budget,
model allowlist and rate limits). One request per connection, bounded head and body, nothing about content is logged.
"""
import asyncio
import re
import sys

LISTEN = ('10.77.0.1', 4000)
UPSTREAM = ('127.0.0.1', 4000)
ALLOWED = {('POST', '/chat/completions'), ('POST', '/v1/chat/completions'), ('GET', '/v1/models'), ('GET', '/models')}
MAX_CONNECTIONS = 64
MAX_HEAD = 16 * 1024
MAX_BODY = 32 * 1024 * 1024          # large enough for images in a prompt
IDLE_SECONDS = 600
BUFFER = 65536
HOP = {'connection', 'keep-alive', 'proxy-connection', 'te', 'trailer', 'upgrade', 'proxy-authorization', 'content-length'}
REQUEST_LINE = re.compile(rb'^([A-Z]{3,7}) (/[!-~]*) HTTP/1\.[01]$')


class Refused(Exception):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason


def parse_head(head):
    """-> (method, path, headers[list of (name, value)], content_length) or raises Refused."""
    lines = head.split(b'\r\n')
    m = REQUEST_LINE.match(lines[0])
    if not m:
        raise Refused(400, 'bad request')
    method, target = m.group(1).decode(), m.group(2).decode('ascii', 'replace')
    path = target.split('?', 1)[0]
    if '%' in path or '..' in path or '//' in path or (method, path) not in ALLOWED:
        raise Refused(403, 'route not available')
    headers, length = [], 0
    for raw in lines[1:]:
        if b':' not in raw:
            raise Refused(400, 'bad header')
        name, value = raw.split(b':', 1)
        name, value = name.strip().decode('ascii', 'replace'), value.strip().decode('latin-1')
        low = name.lower()
        if low == 'transfer-encoding' or low == 'expect':
            raise Refused(411, 'content-length required')
        if low == 'content-length':
            if not value.isdecimal() or int(value) > MAX_BODY:
                raise Refused(413, 'body too large')
            length = int(value)
        if low not in HOP:
            headers.append((name, value))
    if method == 'POST' and length == 0:
        raise Refused(411, 'content-length required')
    return method, target, headers, length


def refusal(status, reason):
    body = ('{"error":"%s"}' % reason).encode()
    return (f'HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n').encode() + body


async def pipe_response(reader, writer):
    while True:
        chunk = await asyncio.wait_for(reader.read(BUFFER), IDLE_SECONDS)
        if not chunk:
            return
        writer.write(chunk)
        await writer.drain()


async def handle(reader, writer, state, upstream):
    if state['open'] >= MAX_CONNECTIONS:
        writer.close()
        return
    state['open'] += 1
    up_writer = None
    try:
        try:
            head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 30)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
            raise Refused(400, 'bad request')
        if len(head) > MAX_HEAD:
            raise Refused(431, 'headers too large')
        method, target, headers, length = parse_head(head[:-4])
        body = await asyncio.wait_for(reader.readexactly(length), IDLE_SECONDS) if length else b''
        up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(*upstream), 5)
        out = f'{method} {target} HTTP/1.1\r\n' + ''.join(f'{n}: {v}\r\n' for n, v in headers) + f'Content-Length: {len(body)}\r\nConnection: close\r\n\r\n'
        up_writer.write(out.encode('latin-1') + body)
        await up_writer.drain()
        await pipe_response(up_reader, writer)
    except Refused as refused:
        writer.write(refusal(refused.status, refused.reason))
        await writer.drain()
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, OSError):
        pass
    finally:
        for w in (up_writer, writer):
            try:
                if w is not None:
                    w.close()
            except Exception:
                pass
        state['open'] -= 1


async def serve(listen=LISTEN, upstream=UPSTREAM):
    state = {'open': 0}
    return await asyncio.start_server(lambda r, w: handle(r, w, state, upstream), *listen, backlog=64, limit=MAX_HEAD + 1024)


async def main():
    server = await serve()
    print(f'relaying {LISTEN} -> {UPSTREAM} (completions and model list only)', flush=True)
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
