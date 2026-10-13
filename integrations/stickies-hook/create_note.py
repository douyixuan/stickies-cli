#!/usr/bin/env python3
"""Prepare a task note without activating apps, using the clipboard, or sending keys.

New notes use the validated stk offline writer under a focus/clipboard guard.
Existing notes are never rewritten or reopened.
"""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
NOTES = Path.home() / 'Library/Containers/com.apple.Stickies/Data/Library/Stickies'
PENDING = ROOT / 'pending'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def recorded(link, notes=NOTES):
    return any(link in path.read_text(errors='ignore') for path in notes.glob('*.rtfd/TXT.rtf'))


def save_pending(session, payload, link, pending=PENDING):
    """Publish a complete RTF once, with a real hyperlink; preserve earlier content."""
    session = str(uuid.UUID(session))
    pending.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = pending / (session + '.rtf')
    if destination.exists():
        data = destination.read_bytes()
        if b'HYPERLINK' not in data or link.encode() not in data:
            raise ValueError('existing pending file has a different or missing task link; left unchanged')
        return destination
    data = subprocess.run(
        ['/usr/bin/textutil', '-convert', 'rtf', '-stdout', '-format', 'html', '-stdin'],
        input=base64.b64decode(payload['data_base64']), capture_output=True, check=True, timeout=20).stdout
    if b'HYPERLINK' not in data or link.encode() not in data:
        raise ValueError('RTF conversion did not preserve the task hyperlink')
    fd, temporary = tempfile.mkstemp(prefix='.note-', dir=pending)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)  # Atomic publication, never replace another writer.
        except FileExistsError:
            existing = destination.read_bytes()
            if b'HYPERLINK' not in existing or link.encode() not in existing:
                raise ValueError('concurrent pending file has a different task link; left unchanged')
    finally:
        os.unlink(temporary)
    return destination


def guarded_import(session, payload, link):
    root = Path.home() / 'code/stickies-cli'
    guard = Path.home() / '.stk/focus_guard'
    if not guard.is_file() or not (root / 'background_runtime.py').is_file():
        raise FileNotFoundError('validated stk runtime/focus guard is missing; no UI fallback')
    lines = payload['also_text'].split('\n')
    request = {'title': lines[0], 'label': lines[1], 'body': '\n'.join(lines[2:]), 'url': link}
    reports = ROOT / 'validation' / str(uuid.UUID(session))
    reports.mkdir(parents=True, exist_ok=True)
    request_path, result_path, focus_path = (reports / name for name in ('request.json', 'result.json', 'focus.json'))
    request_path.write_text(json.dumps(request, ensure_ascii=False))
    completed = subprocess.run([str(guard), str(focus_path), '/usr/bin/python3',
        str(root / 'background_runtime.py'), str(request_path), str(result_path)],
        capture_output=True, text=True, timeout=90)
    result = json.loads(result_path.read_text()) if result_path.exists() else {}
    focus = json.loads(focus_path.read_text()) if focus_path.exists() else {}
    if completed.returncode != 0 or not focus.get('passed') or result.get('status') not in ('created', 'exists'):
        raise RuntimeError('background validation failed; no retry or foreground fallback; reports: ' + str(reports))
    return {'status': result['status'], 'reason': None, 'uuid': result['uuid'], 'reports': str(reports)}


def create(session, payload, link, notes=NOTES, pending=PENDING, backend=None):
    # A failed attempt is latched until explicitly inspected. Never silently bless a partial import.
    blocked = ROOT / 'validation' / str(uuid.UUID(session)) / 'blocked'
    if notes == NOTES and blocked.exists():
        return {'status': 'unavailable', 'reason': 'previous import needs inspection; no retry: ' + str(blocked.parent)}
    if recorded(link, notes):
        return {'status': 'exists', 'reason': None}
    path = save_pending(session, payload, link, pending)
    if backend is not None or notes == NOTES:
        try:
            return (backend or guarded_import)(session, payload, link)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            if notes == NOTES:
                blocked.parent.mkdir(parents=True, exist_ok=True)
                blocked.write_text(str(error))
            return {'status': 'unavailable', 'reason': str(error), 'pending_file': str(path)}
    return {'status': 'unavailable', 'reason': 'isolated pending file only; no desktop runtime', 'pending_file': str(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', required=True)
    for name in ('title', 'progress', 'next-step'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--url')
    parser.add_argument('--label', default='返回 Codex 任务')
    args = parser.parse_args()
    hook, prepare = load('hook'), load('prepare_payload')
    receipt = json.loads(args.receipt)
    result = {'status': 'unavailable', 'reason': None}
    try:
        payload = prepare.prepare(receipt['session'], args.title, args.progress, args.next_step, args.url, args.label)
        link = args.url or 'codex://threads/' + str(uuid.UUID(receipt['session']))
        if not hook.acquire(receipt):
            raise RuntimeError('another task holds the desktop lease; no action')
        result = create(receipt['session'], payload, link)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        result['reason'] = str(error)
    hook.record(receipt, result['status'])
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result['status'] in ('created', 'exists') else 1)


if __name__ == '__main__':
    main()
