"""Experimental offline Stickies creation. Never sends UI events or restarts apps."""
import copy
import fcntl
import hashlib
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit
import uuid

LIVE = Path.home() / 'Library/Containers/com.apple.Stickies/Data/Library/Stickies'
NAMESPACE = uuid.UUID('9a72df70-ae15-4e17-b424-e1caa1821bb8')


def rtf_escape(text):
    out = []
    for unit in memoryview(text.encode('utf-16-le')).cast('H'):
        if unit in (92, 123, 125):
            out.append('\\' + chr(unit))
        elif unit == 10:
            out.append('\\par\n')
        elif unit == 9:
            out.append('\\tab ')
        elif 32 <= unit < 127:
            out.append(chr(unit))
        else:
            out.append('\\u%d?' % (unit if unit < 32768 else unit - 65536))
    return ''.join(out)


def make_rtf(title, body, url, label):
    parsed = urlsplit(url)
    if parsed.scheme not in ('codex', 'claude', 'https', 'http') or not parsed.netloc:
        raise ValueError('link must be an absolute codex, claude, https or http URL')
    if any(c in url for c in '\\{}"\r\n') or not url.isascii() or any(ord(c) <= 32 for c in url):
        raise ValueError('URL must be ASCII and must not contain RTF controls or whitespace')
    if not title.strip() or not label.strip():
        raise ValueError('title and link label are required')
    markup = ('{\\rtf1\\ansi\\deff0\\uc1{\\fonttbl{\\f0 Helvetica;}}\\f0\\fs24 '
              + rtf_escape(title) + '\\par\n'
              + '{\\field{\\*\\fldinst HYPERLINK "' + url + '"}{\\fldrslt '
              + rtf_escape(label) + '}}\\par\n' + rtf_escape(body) + '}')
    return markup.encode('ascii')


def running():
    result = subprocess.run(['/usr/bin/pgrep', '-x', 'Stickies'], capture_output=True, timeout=5)
    if result.returncode not in (0, 1):
        raise RuntimeError('cannot determine whether Stickies is running')
    return result.returncode == 0


def digest(data):
    return hashlib.sha256(data).hexdigest()


def publish_file(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.stk-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create(store, title, body, url, label='返回任务', apply=False, is_running=running):
    store = Path(store).expanduser().resolve()
    live = store == LIVE.resolve()
    data = make_rtf(title, body, url, label)
    identity = str(uuid.uuid5(NAMESPACE, url)).upper()
    result = dict(status='planned', uuid=identity, store=str(store), ui_verified=False,
                  requires_next_launch=True, live_store=live)
    # Keep dry-run entirely read-only. Even lock files are created only on apply.
    if not apply:
        return result
    if live and is_running():
        raise RuntimeError('Stickies is running; no files changed. Quit it yourself before offline import.')
    if not store.is_dir():
        raise ValueError('store must be an existing directory')
    with (store / '.stk-create.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if live and is_running():
            raise RuntimeError('Stickies started before import; no note files changed')
        state_path = store / '.SavedStickiesState'
        original = state_path.read_bytes() if state_path.exists() else None
        state = plistlib.loads(original) if original is not None else []
        if not isinstance(state, list) or any(not isinstance(s, dict) or not isinstance(s.get('UUID'), str) for s in state):
            raise ValueError('unsupported Stickies state format; no note files changed')
        # Find older UUIDs too; do not duplicate a task created by another tool.
        for path in store.glob('*.rtfd/TXT.rtf'):
            if ('HYPERLINK "' + url + '"').encode() in path.read_bytes():
                if not any(s['UUID'] == path.parent.stem for s in state):
                    raise RuntimeError('matching RTF is not indexed; manual recovery required')
                return dict(result, status='exists', uuid=path.parent.stem)
        destination = store / (identity + '.rtfd')
        if destination.exists() or any(s['UUID'] == identity for s in state):
            raise RuntimeError('UUID collision or interrupted import; existing data left unchanged')
        # Copy only style from a real note. Never alter any existing state entry.
        entry = {k: copy.deepcopy(v) for k, v in (state[0] if state else {}).items()
                 if k in ('ControlColor', 'HighlightColor', 'SpineColor', 'StickyColor', 'SpellCheckingTypes')}
        entry.update(UUID=identity, Frame='{{40, 40}, {300, 200}}', ExpandedSize='{300, 200}',
                     ExpandFrameY=0.0, Floating=True, Translucent=False,
                     ZOrder=max((s.get('ZOrder', 0) for s in state), default=0) + 1)
        updated = plistlib.dumps(state + [entry], fmt=plistlib.FMT_BINARY)
        backup = store / '.stk-backups'
        backup.mkdir(mode=0o700, exist_ok=True)
        if original is not None:
            target = backup / ('SavedStickiesState.' + digest(original))
            if not target.exists():
                with target.open('xb') as stream:
                    stream.write(original)
        stage = Path(tempfile.mkdtemp(prefix='.stk-note-', dir=store))
        published = False
        try:
            (stage / 'TXT.rtf').write_bytes(data)
            if live and is_running():
                raise RuntimeError('Stickies started during staging; no note files changed')
            current = state_path.read_bytes() if state_path.exists() else None
            if current != original:
                raise RuntimeError('Stickies state changed during staging; import aborted')
            os.rename(stage, destination)
            published = True
            try:
                publish_file(state_path, updated)
            except BaseException:
                # Only remove the bundle this call just created, never user-owned notes.
                shutil.rmtree(destination)
                raise
        finally:
            if not published:
                shutil.rmtree(stage)
        return dict(result, status='stored', file=str(destination / 'TXT.rtf'),
                    state_backup=str(backup / ('SavedStickiesState.' + digest(original))) if original else None)
