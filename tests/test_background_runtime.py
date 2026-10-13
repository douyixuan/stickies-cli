import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import background_runtime as runtime

class RuntimeTests(unittest.TestCase):
    def test_existing_task_does_not_restart_or_write(self):
        with tempfile.TemporaryDirectory() as directory:
            live = Path(directory)
            note = live / 'original.rtfd'
            note.mkdir()
            file = note / 'TXT.rtf'
            file.write_text('HYPERLINK "codex://threads/example"')
            with patch.object(runtime, 'LIVE', live), patch.object(runtime, 'call', side_effect=AssertionError('unexpected UI process')):
                result = runtime.execute({'title':'T','url':'codex://threads/example'})
            self.assertEqual(result['status'], 'exists')
            self.assertFalse(result['restarted'])
            self.assertEqual(file.read_text(), 'HYPERLINK "codex://threads/example"')

    def test_duplicate_links_fail_before_ui(self):
        with tempfile.TemporaryDirectory() as directory:
            live = Path(directory)
            for name in ('a', 'b'):
                folder = live / (name + '.rtfd'); folder.mkdir()
                (folder/'TXT.rtf').write_text('codex://threads/example')
            with patch.object(runtime, 'LIVE', live), patch.object(runtime, 'call', side_effect=AssertionError('unexpected UI process')):
                with self.assertRaisesRegex(RuntimeError, 'multiple'):
                    runtime.execute({'title':'T','url':'codex://threads/example'})

    def test_partial_accessibility_snapshot_cannot_pass(self):
        responses = [json.dumps({'data':{'windows':[{'window_title':'T…','window_id':1}]}}),
                     json.dumps({'data':{'snapshot_reusable':False,'ui_elements':[{'ax_role':'AXLink'},{'ax_role':'AXTextArea','value':'T\nbody'}]}})] * 10
        with patch.object(runtime, 'call', side_effect=responses), patch.object(runtime.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'readback'):
                runtime.visible('T','codex://threads/example')
