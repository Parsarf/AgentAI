"""Retrieve and verify a backup set before anything is restored from it.

Order of trust: manifest says complete -> every ciphertext matches the recorded size and sha256
(damage is rejected before decryption) -> decrypt with the owner's identity -> plain hash matches ->
the type-specific verifier accepts it. Anything off aborts with a named reason and no plain file is kept.
"""
import json
from pathlib import Path

from .backup import SET_ID, VERIFIERS, sha256_file
from .crypto import AgeCrypto, CryptoError


class SetError(Exception): pass


def load_manifest(destination, set_id):
    if not SET_ID.fullmatch(set_id): raise SetError('invalid set id')
    try: manifest = json.loads(destination.read(f'sets/{set_id}/manifest.json'))
    except (OSError, ValueError, KeyError) as exc:
        raise SetError('manifest missing or unreadable (set is incomplete)') from exc
    if manifest.get('set_id') != set_id: raise SetError('manifest does not belong to this set')
    return manifest


def newest_complete(destination):
    sets = sorted({n.split('/')[1] for n, _, _ in destination.list('sets/') if n.endswith('/manifest.json') and SET_ID.fullmatch(n.split('/')[1])}, reverse=True)
    for sid in sets:
        try:
            if load_manifest(destination, sid).get('complete'): return sid
        except SetError: continue
    return None


def fetch(destination, set_id, identity_file, out_dir, *, only=None, crypto=None, allow_incomplete=False):
    manifest = load_manifest(destination, set_id)
    if not manifest.get('complete') and not allow_incomplete: raise SetError('set is marked incomplete')
    out = Path(out_dir); out.mkdir(mode=0o700, parents=True, exist_ok=True)
    crypto = crypto or AgeCrypto(['age1' + 'q' * 58], binary='age')   # recipients unused for decryption
    got = {}
    for art in manifest['artifacts']:
        if only and art['source'] not in only and art['name'] not in only: continue
        key = f"sets/{set_id}/{art['name']}"
        size = destination.size(key)
        if size is None: raise SetError(f"artifact missing: {art['source']}")
        if size != art['bytes']: raise SetError(f"artifact size differs from the manifest: {art['source']}")
        staged = out / (art['name'])
        with open(staged, 'wb') as handle: handle.write(destination.read(key))
        if sha256_file(staged) != art['sha256']:
            staged.unlink(); raise SetError(f"artifact damaged (ciphertext hash mismatch): {art['source']}")
        plain = out / art['name'][:-4]
        try: crypto.decrypt(staged, plain, identity_file)
        except CryptoError as exc:
            staged.unlink(); raise SetError(f"cannot decrypt {art['source']}: {exc}") from exc
        staged.unlink()
        if sha256_file(plain) != art['plain_sha256']:
            plain.unlink(); raise SetError(f"decrypted content differs from the recorded hash: {art['source']}")
        try: VERIFIERS[art['kind']](plain)
        except Exception as exc:
            plain.unlink(); raise SetError(f"verification failed after decryption: {art['source']}") from exc
        got[art['source']] = plain
    if only and not got: raise SetError('nothing matched the requested artifacts')
    return manifest, got
