// A WebSocket server with no dependencies (text frames only), for the local development bridge. The platform's own gateway replaces it.
import http from 'node:http';
import { createHash } from 'node:crypto';

const GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';
const MAX_MESSAGE = 32 * 1024 * 1024;

export function wsServer({ port = 0, host = '127.0.0.1', path = '/device', onConnection }) {
  const server = http.createServer((req, res) => { res.writeHead(426); res.end('websocket only'); });
  server.on('upgrade', (req, socket) => {
    if (new URL(req.url, 'http://x').pathname !== path || !req.headers['sec-websocket-key']) return socket.destroy();
    const accept = createHash('sha1').update(req.headers['sec-websocket-key'] + GUID).digest('base64');
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
    onConnection(connection(socket, req));
  });
  return new Promise(resolve => server.listen(port, host, () => resolve({ server, port: server.address().port, close: () => { server.closeAllConnections?.(); server.close(); } })));
}

function frame(opcode, payload) {
  const n = payload.length;
  const head = n < 126 ? Buffer.from([0x80 | opcode, n]) : n < 65536 ? Buffer.from([0x80 | opcode, 126, n >> 8, n & 255]) : (() => { const b = Buffer.alloc(10); b[0] = 0x80 | opcode; b[1] = 127; b.writeBigUInt64BE(BigInt(n), 2); return b; })();
  return Buffer.concat([head, payload]);
}

function connection(socket, req) {
  let buf = Buffer.alloc(0), parts = [], size = 0, onMessage = () => {}, onClose = () => {}, closed = false;
  const end = () => { if (!closed) { closed = true; onClose(); } };
  socket.on('data', chunk => {
    buf = Buffer.concat([buf, chunk]);
    for (;;) {
      if (buf.length < 2) return;
      const fin = !!(buf[0] & 0x80), opcode = buf[0] & 15, masked = !!(buf[1] & 0x80);
      let len = buf[1] & 127, at = 2;
      if (len === 126) { if (buf.length < 4) return; len = buf.readUInt16BE(2); at = 4; }
      else if (len === 127) { if (buf.length < 10) return; len = Number(buf.readBigUInt64BE(2)); at = 10; }
      if (len > MAX_MESSAGE || !masked) return socket.destroy();      // clients must mask; nothing bigger than a few pictures is ever sent
      if (buf.length < at + 4 + len) return;
      const mask = buf.subarray(at, at + 4), data = Buffer.from(buf.subarray(at + 4, at + 4 + len));
      for (let i = 0; i < len; i++) data[i] ^= mask[i & 3];
      buf = buf.subarray(at + 4 + len);
      if (opcode === 8) { socket.end(frame(8, Buffer.alloc(0))); return end(); }
      if (opcode === 9) { socket.write(frame(10, data)); continue; }
      if (opcode === 10) continue;
      parts.push(data); size += len;
      if (size > MAX_MESSAGE) return socket.destroy();
      if (fin) { const text = Buffer.concat(parts).toString('utf8'); parts = []; size = 0; onMessage(text); }
    }
  });
  socket.on('close', end); socket.on('error', end);
  return {
    headers: req.headers,
    send: text => { if (!closed) socket.write(frame(1, Buffer.from(text))); },
    close: () => { if (!closed) { socket.end(frame(8, Buffer.alloc(0))); end(); } },
    onMessage: fn => { onMessage = fn; }, onClose: fn => { onClose = fn; },
  };
}
