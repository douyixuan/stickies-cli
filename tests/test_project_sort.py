import importlib.machinery
import importlib.util
from pathlib import Path
import unittest

loader = importlib.machinery.SourceFileLoader('stk', str(Path(__file__).resolve().parents[1] / 'stk'))
spec = importlib.util.spec_from_loader('stk', loader)
stk = importlib.util.module_from_spec(spec)
loader.exec_module(stk)


class ProjectTests(unittest.TestCase):
    def test_project_names(self):
        cases = {
            'Multica｜IT 交接会议材料': 'Multica',
            'Multica / 邮箱登录｜配置邮箱 SMTP 登录入口': 'Multica',
            '？Multica｜18000 升级主线（原会话）': 'Multica',
            ' App 平台｜181/182 统一部署与维护': 'App 平台',
            'Triton / CodeChecker｜codecheck 优化': 'Triton',
            'Multica ': 'Multica',
            'u22｜Codex CLI 与服务检查': 'u22',
        }
        for title, name in cases.items():
            self.assertEqual(stk.project(title), name, title)

    def test_empty_note_sorts_last(self):
        self.assertGreater(stk.project('(empty)'), stk.project('Triton｜x'))


if __name__ == '__main__':
    unittest.main()
