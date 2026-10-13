import plistlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import background_note as note

URL = 'codex://threads/01a13369-8b4d-73d2-b61c-f9cb1c1526fa'


class CreateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name)
        self.original = [{'UUID': 'EXISTING', 'Frame': '{{8, 677}, {300, 200}}', 'Floating': False, 'ZOrder': 1}]
        self.state = self.store / '.SavedStickiesState'
        self.state.write_bytes(plistlib.dumps(self.original, fmt=plistlib.FMT_BINARY))
        old = self.store / 'EXISTING.rtfd'
        old.mkdir()
        (old / 'TXT.rtf').write_bytes(b'user-owned RTF')

    def create(self, **kwargs):
        return note.create(self.store, '中文 🧪 {title}', 'line 1\n下一步 \\ done', URL, **kwargs)

    def test_dry_run_writes_nothing(self):
        before = sorted(self.store.rglob('*'))
        self.assertEqual(self.create()['status'], 'planned')
        self.assertEqual(before, sorted(self.store.rglob('*')))

    def test_native_rtf_decode_and_existing_notes_unchanged(self):
        old = self.state.read_bytes()
        with patch.object(note.subprocess, 'run', side_effect=AssertionError('no subprocess during isolated creation')):
            result = self.create(apply=True)
        self.assertEqual(result['status'], 'stored')
        rtf = Path(result['file'])
        text = subprocess.run(['/usr/bin/textutil', '-convert', 'txt', '-stdout', str(rtf)], capture_output=True, check=True).stdout.decode()
        self.assertEqual(text, '中文 🧪 {title}\n返回任务\nline 1\n下一步 \\ done')
        self.assertIn(b'HYPERLINK "' + URL.encode() + b'"', rtf.read_bytes())
        self.assertEqual(plistlib.loads(self.state.read_bytes())[:-1], self.original)
        self.assertEqual((self.store / 'EXISTING.rtfd/TXT.rtf').read_bytes(), b'user-owned RTF')
        self.assertEqual(Path(result['state_backup']).read_bytes(), old)
        self.assertFalse(result['ui_verified'])

    def test_dedupe_keeps_original_content(self):
        first = self.create(apply=True)
        original = Path(first['file']).read_bytes()
        result = note.create(self.store, 'replacement', 'new', URL, apply=True)
        self.assertEqual(result['status'], 'exists')
        self.assertEqual(Path(first['file']).read_bytes(), original)
        self.assertEqual(len(plistlib.loads(self.state.read_bytes())), 2)

    def test_running_app_is_refused_before_any_write(self):
        with patch.object(note, 'LIVE', self.store):
            before = sorted(self.store.rglob('*'))
            with self.assertRaisesRegex(RuntimeError, 'running'):
                self.create(apply=True, is_running=lambda: True)
            self.assertEqual(before, sorted(self.store.rglob('*')))

    def test_state_write_failure_rolls_back_only_new_bundle(self):
        original = self.state.read_bytes()
        with patch.object(note, 'publish_file', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.create(apply=True)
        self.assertEqual(self.state.read_bytes(), original)
        self.assertEqual([p.name for p in self.store.glob('*.rtfd')], ['EXISTING.rtfd'])

    def test_corrupt_state_is_not_overwritten(self):
        self.state.write_bytes(b'corrupt')
        with self.assertRaises(plistlib.InvalidFileException):
            self.create(apply=True)
        self.assertEqual(self.state.read_bytes(), b'corrupt')

    def test_injection_url_is_rejected(self):
        for url in ['javascript:alert(1)', URL + '"}', URL + '\n', 'https://x/中']:
            with self.assertRaises(ValueError):
                note.make_rtf('Title', 'Body', url, 'Link')

    def test_orphan_requires_recovery_not_duplicate(self):
        result = self.create(apply=True)
        self.state.write_bytes(plistlib.dumps(self.original))
        with self.assertRaisesRegex(RuntimeError, 'manual recovery'):
            self.create(apply=True)
        self.assertTrue(Path(result['file']).exists())


if __name__ == '__main__':
    unittest.main()
