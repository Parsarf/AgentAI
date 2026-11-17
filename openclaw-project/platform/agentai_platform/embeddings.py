"""Vectors for search by meaning (roadmap #36, #37). Stdlib only.

Production: a self-hosted embedding server on the Lumina host (Hugging Face text-embeddings-inference, CPU, the multilingual E5 small model, bound to 127.0.0.1;
deploy/knowledge/install.sh). The owner chose self-hosted on 2026-11-16 so that the customer's documents never leave the server to be embedded.

`HashEmbedder` is a deterministic stand-in with the same interface (words and three-letter pieces hashed into the same number of dimensions). It is used by the
tests and by the local development server, never as a quiet fallback in production: with no embedding server configured the knowledge feature is unavailable.
"""
from __future__ import annotations
import hashlib
import http.client
import json
import math
import re
from urllib.parse import urlsplit

from .adapters import CapabilityUnavailable

DIMENSIONS = 384
BATCH = 32
MAX_CHARS = 2000                     # what one passage contributes to its vector (the server truncates to the model's own limit as well)
WORD = re.compile(r'\w+', re.UNICODE)


def _normalise(vector):
    size = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / size for v in vector]


def cosine(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


class HashEmbedder:
    """Deterministic vectors: each word and each three-letter piece of a word adds +1 or -1 to one dimension. Similar wording gives similar vectors; it knows no synonyms."""
    name = 'hash-v1'

    def __init__(self, dims=DIMENSIONS):
        self.dims = dims

    def _one(self, text):
        vector = [0.0] * self.dims
        for word in WORD.findall((text or '').lower()[:MAX_CHARS]):
            pieces = [word] + ([word[i:i + 3] for i in range(len(word) - 2)] if len(word) > 3 else [])
            for n, piece in enumerate(pieces):
                digest = hashlib.blake2b(piece.encode(), digest_size=8).digest()
                slot, sign = int.from_bytes(digest[:4], 'big') % self.dims, 1.0 if digest[4] & 1 else -1.0
                vector[slot] += sign * (2.0 if n == 0 else 0.5)
        return _normalise(vector)

    def passages(self, texts):
        return [self._one(t) for t in texts]

    def query(self, text):
        return self._one(text)


class TeiEmbedder:
    """text-embeddings-inference on a loopback address. E5 models want "query: " and "passage: " in front of what they embed."""
    name = 'e5-small-tei'

    def __init__(self, url, *, dims=DIMENSIONS, timeout=60, connect=http.client.HTTPConnection):
        parts = urlsplit(url)
        if parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost', '::1') or not parts.port:
            raise ValueError('the embedding server must be on this host')
        self.host, self.port, self.dims, self.timeout, self._connect = parts.hostname, parts.port, dims, timeout, connect

    def _embed(self, inputs):
        out = []
        for start in range(0, len(inputs), BATCH):
            batch = [s[:MAX_CHARS] for s in inputs[start:start + BATCH]]
            conn = self._connect(self.host, self.port, timeout=self.timeout)
            try:
                conn.request('POST', '/embed', json.dumps({'inputs': batch, 'normalize': True, 'truncate': True}), {'Content-Type': 'application/json'})
                response = conn.getresponse()
                body = response.read(64 * 1024 * 1024)
            except OSError as exc:
                raise CapabilityUnavailable('embedding server unavailable') from exc
            finally:
                conn.close()
            if response.status != 200:
                raise CapabilityUnavailable(f'embedding server answered {response.status}')
            try:
                vectors = json.loads(body)
            except ValueError as exc:
                raise CapabilityUnavailable('embedding server reply invalid') from exc
            if not isinstance(vectors, list) or len(vectors) != len(batch) or any(not isinstance(v, list) or len(v) != self.dims for v in vectors):
                raise CapabilityUnavailable('embedding server reply invalid')
            out.extend([float(x) for x in v] for v in vectors)
        return out

    def passages(self, texts):
        return self._embed(['passage: ' + (t or '') for t in texts]) if texts else []

    def query(self, text):
        return self._embed(['query: ' + (text or '')])[0]
