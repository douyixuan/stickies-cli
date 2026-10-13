#!/usr/bin/env python3
"""Prepare an ASCII HTML payload for a new note. Does not access the desktop."""
import argparse
import base64
import html
import json
import re
import shutil
import uuid
from pathlib import Path


def resolve_peekaboo():
    candidate = shutil.which('peekaboo')
    if candidate:
        return candidate
    for candidate in ('/opt/homebrew/bin/peekaboo', '/usr/local/bin/peekaboo'):
        if Path(candidate).is_file():
            import os
            if os.access(candidate, os.X_OK):
                return candidate
    raise FileNotFoundError('Peekaboo executable not found')


CLAUDE_URL = re.compile(r'^claude://code/continue\?session=local_[A-Za-z0-9-]{1,64}$')


def prepare(session, title, progress, next_step, url=None, label='返回 Codex 任务'):
    session = str(uuid.UUID(session))
    if url is None:
        url = 'codex://threads/' + session
    elif not CLAUDE_URL.match(url):
        raise ValueError('unsupported task link')
    text = '\n'.join((title, label, progress, next_step))
    markup = ('<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
              '<p>' + html.escape(title) + '</p><p><a href="' + url + '">' + html.escape(label) + '</a></p>'
              '<p>' + html.escape(progress) + '</p><p>' + html.escape(next_step) + '</p></body></html>')
    payload = markup.encode('ascii', 'xmlcharrefreplace')
    encoded = base64.b64encode(payload).decode('ascii')
    return {'uti': 'public.html', 'data_base64': encoded, 'also_text': text}



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('session', 'title', 'progress', 'next-step'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--url', help='Claude desktop task link from the hook context')
    parser.add_argument('--label', default='返回 Codex 任务')
    args = parser.parse_args()
    print(json.dumps(prepare(args.session, args.title, args.progress, args.next_step, args.url, args.label), ensure_ascii=False))
