"""Guarded lifecycle and local readback for create-only Stickies imports."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import time
import uuid
from background_note import LIVE, create, running


def call(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=30).stdout


def hashes():
    return {str(p.relative_to(LIVE)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in LIVE.glob('*.rtfd/**/*') if p.is_file()}


def state():
    return plistlib.loads((LIVE / '.SavedStickiesState').read_bytes())


def visible(title, url):
    peek = shutil.which('peekaboo') or '/opt/homebrew/bin/peekaboo'
    for _ in range(10):
        data = json.loads(call(peek, 'window', 'list', '--app', 'Stickies', '--no-remote', '--json'))
        for window in (data.get('data') or {}).get('windows', []):
            if not window.get('window_title', '').startswith(title):
                continue
            snapshot = json.loads(call(peek, 'see', '--app', 'Stickies', '--window-id', str(window['window_id']),
                                      '--tree', '--no-screenshot', '--no-remote', '--json'))
            content = snapshot.get('data') or {}
            elements = content.get('ui_elements', [])
            if content.get('snapshot_reusable') and any(e.get('ax_role') == 'AXLink' for e in elements) and any(
                e.get('ax_role') == 'AXTextArea' and (e.get('value') or '').startswith(title + '\n') for e in elements):
                return window['window_id']
        time.sleep(.3)
    raise RuntimeError('new note did not pass local window/link readback; do not recreate')


def execute(request, verify_restart=False):
    title, url = request['title'], request['url']
    matches = [p for p in LIVE.glob('*.rtfd/TXT.rtf') if url in p.read_text(errors='ignore')]
    if len(matches) > 1:
        raise RuntimeError('multiple notes match this task; nothing changed')
    if matches and not verify_restart:
        return {'status': 'exists', 'uuid': matches[0].parent.stem, 'restarted': False}
    if verify_restart and len(matches) != 1:
        raise RuntimeError('restart verification requires exactly one existing note')
    before = hashes()
    backup = Path.home() / '.stk/import-backups' / str(uuid.uuid4())
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(LIVE, backup, ignore=shutil.ignore_patterns('.stk-backups', '.stk-create.lock'))
    was_running = running()
    quit_sent = False
    try:
        if was_running:
            call('/usr/bin/osascript', '-e', 'tell application "Stickies" to quit')
            quit_sent = True
            for _ in range(100):
                if not running(): break
                time.sleep(.1)
            else: raise RuntimeError('Stickies did not quit; no import')
        saved = hashes()
        if saved != before:
            raise RuntimeError('notes changed while quitting; saved user edits kept, no import')
        baseline = state()
        if verify_restart:
            result = {'status': 'exists', 'uuid': matches[0].parent.stem}
        else:
            result = create(LIVE, title, request['body'], url, request['label'], apply=True)
        now = hashes()
        current = {s['UUID']: s for s in state()}
        if any(now.get(p) != h for p, h in saved.items()) or any(current.get(s['UUID']) != s for s in baseline):
            raise RuntimeError('existing-note preservation check failed; backup retained')
    finally:
        if quit_sent or not was_running:
            # LaunchServices background delivery only. Never restore/activate foreground.
            call('/usr/bin/open', '-g', '-a', 'Stickies')
    window = visible(title, url)
    now = hashes()
    current = {s['UUID']: s for s in state()}
    if any(now.get(p) != h for p, h in saved.items()) or any(current.get(s['UUID']) != s for s in baseline):
        raise RuntimeError('existing notes changed after restart; no automatic restore')
    return dict(result, status='exists' if verify_restart else 'created', window_id=window,
                restarted=was_running, preservation_passed=True, backup=str(backup))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('request')
    parser.add_argument('result')
    parser.add_argument('--verify-restart', action='store_true')
    args = parser.parse_args()
    try:
        result = execute(json.loads(Path(args.request).read_text()), args.verify_restart)
        code = 0
    except Exception as error:
        result = {'status': 'unavailable', 'reason': str(error)}
        code = 1
    Path(args.result).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(code)
