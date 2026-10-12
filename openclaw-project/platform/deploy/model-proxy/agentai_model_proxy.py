#!/usr/bin/env python3
"""Layer-4 forwarder: the only door from customer cells to the model proxy.

Listens on the cell bridge address (10.77.0.1:4000), which the host firewall allows cells to reach, and relays
bytes to the model proxy's loopback port. It adds no authority: LiteLLM still authenticates every request with the
cell's own virtual key, which carries its own budget, model allowlist and rate limits. The relay refuses any other
upstream, caps concurrent connections and idle time, and logs nothing about content.
"""
import asyncio
import sys

LISTEN = ('10.77.0.1', 4000)
UPSTREAM = ('127.0.0.1', 4000)
MAX_CONNECTIONS = 64
IDLE_SECONDS = 600
BUFFER = 65536


async def pipe(reader, writer):
    try:
        while True:
            chunk = await asyncio.wait_for(reader.read(BUFFER), IDLE_SECONDS)
            if not chunk: break
            writer.write(chunk); await writer.drain()
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    finally:
        try: writer.close()
        except Exception: pass


async def handle(reader, writer, state):
    if state['open'] >= MAX_CONNECTIONS:
        writer.close(); return
    state['open'] += 1
    try:
        up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(*UPSTREAM), 5)
        await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))
    except (asyncio.TimeoutError, OSError):
        writer.close()
    finally:
        state['open'] -= 1


async def main():
    state = {'open': 0}
    server = await asyncio.start_server(lambda r, w: handle(r, w, state), *LISTEN, backlog=64)
    print(f'relaying {LISTEN} -> {UPSTREAM}', flush=True)
    async with server: await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
