"""Regressions for encoding and first-creation instructions. No desktop access."""
import base64
import html
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SESSION = '01a11a46-c551-73f1-b4c0-fe3f9824f01d'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


payload = load('prepare_payload')
hook = load('hook')
note = load('create_note')


class PayloadTests(unittest.TestCase):
    def prepare(self, title='Multica｜GitLab 全流程托管'):
        with patch.object(payload, 'resolve_peekaboo', return_value='/opt/homebrew/bin/peekaboo'):
            return payload.prepare(SESSION, title, '进展：中文与 emoji 🧪', '下一步：全局修复')

    def test_ascii_entities_survive_charset_mismatch(self):
        result = self.prepare()
        data = base64.b64decode(result['data_base64'])
        self.assertTrue(data.isascii())
        self.assertIn(b'<meta charset="utf-8">', data)
        for codec in ('utf-8', 'cp1252', 'latin-1'):
            self.assertIn('Multica｜GitLab 全流程托管', html.unescape(data.decode(codec)))

    def test_html_special_characters_do_not_create_tags(self):
        result = self.prepare('<script>中文 & "quoted"</script>')
        data = base64.b64decode(result['data_base64'])
        self.assertNotIn(b'<script>', data)
        self.assertIn(b'&lt;script&gt;', data)
        self.assertIn(b'&amp;', data)

    def test_payload_has_no_ui_delivery_arguments(self):
        result = self.prepare()
        self.assertNotIn('paste_args', result)
        self.assertEqual(len(result['also_text'].splitlines()), 4)
        self.assertNotIn(SESSION, result['also_text'])

    def test_invalid_session_is_rejected(self):
        with self.assertRaises(ValueError):
            payload.prepare('not-a-thread', 'Title', 'Progress', 'Next')

    def test_claude_link_and_label(self):
        url = 'claude://code/continue?session=local_a0d81c34-96a7-49d2-bb8d-b82b25e588b5'
        with patch.object(payload, 'resolve_peekaboo', return_value='/opt/homebrew/bin/peekaboo'):
            result = payload.prepare(SESSION, 'T', 'P', 'N', url, '返回 Claude 任务')
            with self.assertRaises(ValueError):
                payload.prepare(SESSION, 'T', 'P', 'N', 'https://example.com/"><script>')
        data = html.unescape(base64.b64decode(result['data_base64']).decode('ascii'))
        self.assertIn('<a href="' + url + '">返回 Claude 任务</a>', data)
        self.assertNotIn('codex://', data)

    @unittest.skipUnless(Path('/usr/bin/textutil').exists(), 'macOS textutil required')
    def test_native_html_conversion_preserves_text_and_hyperlink(self):
        result = self.prepare()
        data = base64.b64decode(result['data_base64'])
        def convert(fmt):
            return subprocess.run(['/usr/bin/textutil', '-convert', fmt, '-stdout',
                                   '-format', 'html', '-stdin'], input=data,
                                  capture_output=True, check=True).stdout
        self.assertEqual(convert('txt').decode('utf-8').strip(), result['also_text'])
        rtf = convert('rtf')
        self.assertIn(b'HYPERLINK', rtf)
        self.assertIn(('codex://threads/' + SESSION).encode(), rtf)


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.state = self.home / 'hook.sqlite'
        with sqlite3.connect(self.home / 'state_1.sqlite') as db:
            db.execute('CREATE TABLE threads (id TEXT, source TEXT, archived INTEGER)')
            db.execute('INSERT INTO threads VALUES (?, ?, ?)', (SESSION, 'cli', 0))
        self.event = dict(hook_event_name='UserPromptSubmit', session_id=SESSION,
                          turn_id='regression-turn', prompt='Inspect payload encoding')

    def test_instruction_separates_automatic_creation_from_authorized_validation(self):
        result = hook.handle(self.event, state=self.state, home=self.home)
        instruction = result['hookSpecificOutput']['additionalContext']
        self.assertIn('create_note.py --receipt', instruction)
        self.assertIn('"token": "regression-turn"', instruction)
        self.assertIn('background-create-v3', instruction)
        self.assertIn('用户已明确授权便笺工具真实验证时', instruction)
        self.assertIn('既有授权跨轮有效，不重复询问', instruction)
        self.assertIn('不改变已有便笺正文、链接、位置、样式', instruction)
        self.assertIn('均验证通过后，才接入自动 hook', instruction)
        self.assertIn('不重试、不换工具', instruction)

    def test_repeatedly_unavailable_session_is_no_longer_asked(self):
        for attempt in range(hook.ATTEMPTS):
            event = dict(self.event, turn_id='turn-%d' % attempt)
            self.assertTrue(hook.handle(event, state=self.state, home=self.home))
            hook.record({'session': SESSION, 'token': event['turn_id']}, 'unavailable', self.state)
        self.assertEqual(hook.handle(dict(self.event, turn_id='turn-next'), state=self.state, home=self.home), {})

    def test_lease_excludes_other_turns_until_recorded(self):
        first, second = ({'session': SESSION, 'token': token} for token in ('a', 'b'))
        self.assertTrue(hook.acquire(first, self.state))
        self.assertTrue(hook.acquire(first, self.state))
        self.assertFalse(hook.acquire(second, self.state))
        hook.record(first, 'unavailable', self.state)
        self.assertTrue(hook.acquire(second, self.state))

    def test_repeated_turn_does_not_repeat_instruction(self):
        hook.handle(self.event, state=self.state, home=self.home)
        self.assertEqual(hook.handle(self.event, state=self.state, home=self.home), {})

    def test_created_note_is_never_recreated(self):
        with hook.connect(self.state) as db:
            db.execute('INSERT INTO created VALUES (?)', (SESSION,))
        self.assertEqual(hook.handle(self.event, state=self.state, home=self.home), {})

    def test_claude_desktop_session_gets_claude_link(self):
        env = {'CLAUDE_CODE_HOST_SESSION_ID': 'local_abc-123', 'CLAUDE_CODE_SESSION_ATTENDED': '1'}
        event = dict(self.event, session_id=str(hook.uuid.uuid4()))
        event.pop('turn_id')
        result = hook.handle(event, state=self.state, home=self.home, agent='claude', env=env)
        instruction = result['hookSpecificOutput']['additionalContext']
        self.assertIn('claude://code/continue?session=local_abc-123', instruction)
        self.assertIn("--label '返回 Claude 任务'", instruction)
        self.assertNotIn('codex://', instruction)

    def test_claude_without_verified_link_is_skipped(self):
        for env in ({}, {'CLAUDE_CODE_HOST_SESSION_ID': 'local_x; rm'},
                    {'CLAUDE_CODE_HOST_SESSION_ID': 'local_abc', 'CLAUDE_CODE_SESSION_ATTENDED': '0'}):
            self.assertEqual(hook.handle(self.event, state=self.state, home=self.home, agent='claude', env=env), {})


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.notes, self.pending = self.root / 'notes', self.root / 'pending'
        self.notes.mkdir()
        self.link = 'codex://threads/' + SESSION
        self.payload = payload.prepare(SESSION, '后台便笺 🧪', '进展', '下一步')

    def create(self):
        return note.create(SESSION, self.payload, self.link, notes=self.notes, pending=self.pending)

    def test_real_rtf_preserves_unicode_newlines_and_hyperlink_without_ui_calls(self):
        original = subprocess.run
        calls = []
        def only_textutil(command, **kwargs):
            calls.append(command)
            self.assertEqual(command[0], '/usr/bin/textutil')
            return original(command, **kwargs)
        with patch.object(note.subprocess, 'run', side_effect=only_textutil):
            result = self.create()
        self.assertEqual(result['status'], 'unavailable')
        path = Path(result['pending_file'])
        self.assertIn(b'HYPERLINK', path.read_bytes())
        self.assertIn(self.link.encode(), path.read_bytes())
        text = original(['/usr/bin/textutil', '-convert', 'txt', '-stdout', str(path)], capture_output=True, check=True).stdout.decode()
        self.assertEqual(text.strip(), self.payload['also_text'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(list(self.notes.iterdir()), [])

    def test_validated_backend_success_and_failure(self):
        result = note.create(SESSION, self.payload, self.link, notes=self.notes, pending=self.pending,
                             backend=lambda *args: {'status': 'created', 'reason': None})
        self.assertEqual(result['status'], 'created')
        def fail(*args):
            raise RuntimeError('focus changed')
        result = note.create(SESSION, self.payload, self.link, notes=self.notes, pending=self.pending, backend=fail)
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('focus changed', result['reason'])

    def test_repeated_request_preserves_first_pending_file(self):
        first = Path(self.create()['pending_file'])
        before = first.read_bytes(), first.stat().st_mtime_ns
        self.payload = payload.prepare(SESSION, '不同标题', '不同进展', '不同下一步')
        self.create()
        self.assertEqual(before, (first.read_bytes(), first.stat().st_mtime_ns))

    def test_existing_note_needs_no_process_or_pending_file(self):
        saved = self.notes / 'existing.rtfd'
        saved.mkdir()
        (saved / 'TXT.rtf').write_text('HYPERLINK "' + self.link + '"')
        with patch.object(note.subprocess, 'run', side_effect=AssertionError('unexpected process')):
            self.assertEqual(self.create()['status'], 'exists')
        self.assertFalse(self.pending.exists())

    def test_conversion_failure_cannot_publish_or_mark_created(self):
        with patch.object(note.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'no link', b'')):
            with self.assertRaisesRegex(ValueError, 'hyperlink'):
                self.create()
        self.assertEqual(list(self.pending.iterdir()), [])

    def test_existing_invalid_pending_file_is_not_overwritten(self):
        self.pending.mkdir()
        path = self.pending / (SESSION + '.rtf')
        path.write_text('user content')
        with self.assertRaisesRegex(ValueError, 'left unchanged'):
            self.create()
        self.assertEqual(path.read_text(), 'user content')


if __name__ == '__main__':
    unittest.main()
