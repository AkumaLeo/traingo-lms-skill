"""Offline bootstrap tests; no real installs, browser or host probes."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('bootstrap', Path(__file__).resolve().parents[1] / 'scripts/bootstrap.py')
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'requirements.txt').write_text('PyMuPDF>=1.24,<2\n')
        self.output = io.StringIO()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.stack.enter_context(patch.object(b, 'ROOT', self.root))
        self.stack.enter_context(patch.object(b.shutil, 'which', side_effect=lambda name: '/tools/' + name + ('.exe' if sys.platform == 'win32' else '')))
        self.run = self.stack.enter_context(patch.object(b.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)))
        self.create = self.stack.enter_context(patch.object(b.venv.EnvBuilder, 'create', side_effect=self.fake_create))

    def fake_create(self, path):
        path = Path(path)
        (path / 'pyvenv.cfg').write_text('home = synthetic\n')
        python = b.venv_python(path)
        python.parent.mkdir()
        python.touch()

    def owned(self):
        path = self.root / '.venv'
        path.mkdir()
        self.fake_create(path)
        (path / b.MARKER).write_bytes(b.MARKER_VALUE.encode('utf-8'))
        return path

    def test_default_readonly_and_missing_environment(self):
        self.assertEqual(b.main([]), 1)
        self.assertFalse((self.root / '.venv').exists())
        self.create.assert_not_called()
        self.assertFalse(any('pip' in c.args[0] for c in self.run.call_args_list))

    def test_unknown_environment_never_overwritten(self):
        path = self.root / '.venv'
        path.mkdir()
        sentinel = path / 'user-file'
        sentinel.write_text('keep')
        self.assertEqual(b.main(['--install']), 1)
        self.assertEqual(sentinel.read_text(), 'keep')
        self.create.assert_not_called()
        self.assertFalse(any('pip' in c.args[0] for c in self.run.call_args_list))

    def test_explicit_install_is_local_and_idempotent(self):
        self.assertEqual(b.main(['--install']), 0)
        self.assertEqual(b.main(['--install']), 0)
        self.create.assert_called_once()
        calls = [c.args[0] for c in self.run.call_args_list if 'pip' in c.args[0]]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][:4], [str(b.venv_python(self.root / '.venv')), '-I', '-m', 'pip'])
        self.assertIn('--isolated', calls[0])
        self.assertIn('--no-input', calls[0])
        self.assertIn('--retries', calls[0])
        self.assertIn('--timeout', calls[0])
        self.assertNotIn('sudo', calls[0])

    def test_check_uses_venv_help_only(self):
        self.owned()
        self.assertEqual(b.main(['--check']), 0)
        help_calls = [c.args[0] for c in self.run.call_args_list if c.args[0][-1] == '--help']
        self.assertEqual(len(help_calls), 2)
        self.assertTrue(all(c[0] == str(b.venv_python(self.root / '.venv')) for c in help_calls))
        for call in self.run.call_args_list:
            self.assertIs(call.kwargs['shell'], False)
            self.assertGreater(call.kwargs['timeout'], 0)
            self.assertEqual(call.kwargs['stdin'], subprocess.DEVNULL)
            self.assertNotIn('bind', call.args[0])

    def test_missing_tools_actionable_and_no_install(self):
        with patch.object(b.shutil, 'which', return_value=None):
            self.assertEqual(b.main([]), 1)
        for name in ('node', 'npm', 'opencli'):
            self.assertIn(name, self.output.getvalue())
        self.create.assert_not_called()

    def test_old_python_prevents_actions(self):
        with patch.object(b.sys, 'version_info', (3, 8, 0)):
            self.assertEqual(b.main(['--install']), 1)
        self.create.assert_not_called()
        self.run.assert_not_called()

    def test_timeout_and_raw_errors_are_private(self):
        self.run.side_effect = subprocess.TimeoutExpired('PRIVATE', 10, output='SECRET')
        self.assertEqual(b.main([]), 1)
        self.assertNotIn('PRIVATE', self.output.getvalue())
        self.assertNotIn('SECRET', self.output.getvalue())

    def test_install_failure_not_reported_ready(self):
        def result(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1 if 'pip' in argv else 0)
        self.run.side_effect = result
        self.assertEqual(b.main(['--install', '--check']), 1)
        self.assertNotIn('local_dependencies_ready', self.output.getvalue())

    def test_failed_dependency_blocks_smoke(self):
        self.owned()
        self.run.side_effect = lambda argv, **kw: subprocess.CompletedProcess(argv, 1 if '-c' in argv else 0)
        self.assertEqual(b.main(['--check']), 1)
        self.assertFalse(any(c.args[0][-1] == '--help' for c in self.run.call_args_list))

    def test_smoke_failure_does_not_claim_pass(self):
        self.owned()
        self.run.side_effect = lambda argv, **kw: subprocess.CompletedProcess(argv, 1 if argv[-1] == '--help' else 0)
        self.assertEqual(b.main(['--check']), 1)
        self.assertNotIn('smoke_passed', self.output.getvalue())

    def test_unknown_symlink_environment_refused(self):
        other = self.root / 'other'
        other.mkdir()
        try:
            (self.root / '.venv').symlink_to(other, target_is_directory=True)
        except OSError as error:
            if sys.platform == 'win32' and getattr(error, 'winerror', None) == 1314:
                self.skipTest('Windows symlink privilege unavailable')
            raise
        self.assertEqual(b.main(['--install']), 1)
        self.create.assert_not_called()

    def test_pip_does_not_read_user_auth_or_config(self):
        self.assertEqual(b.main(['--install']), 0)
        calls = [c for c in self.run.call_args_list if 'pip' in c.args[0]]
        self.assertEqual(calls[0].kwargs['env']['NETRC'], b.os.devnull)
        self.assertEqual(calls[0].kwargs['env']['PIP_CONFIG_FILE'], b.os.devnull)

    def test_ensurepip_failure_keeps_unowned_partial_environment(self):
        self.run.side_effect = lambda argv, **kw: subprocess.CompletedProcess(argv, 1 if 'ensurepip' in argv else 0)
        self.assertEqual(b.main(['--install']), 1)
        self.assertFalse((self.root / '.venv' / b.MARKER).exists())
        self.assertFalse(any('pip' in c.args[0] for c in self.run.call_args_list))

    def test_marker_write_has_platform_independent_newlines(self):
        original_open = Path.open
        writes = []

        def tracked_open(path, *args, **kwargs):
            if path.name == b.MARKER and args and args[0] == 'x':
                writes.append(kwargs.copy())
            return original_open(path, *args, **kwargs)

        with patch.object(Path, 'open', tracked_open):
            self.assertEqual(b.main(['--install']), 0)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0].get('newline'), '\n')
        self.assertEqual((self.root / '.venv' / b.MARKER).read_bytes(), b.MARKER_VALUE.encode('utf-8'))

    def test_explicit_mirror_only_reaches_isolated_pip_and_is_not_printed(self):
        mirror = 'https://mirror.invalid/private/simple'
        self.assertEqual(b.main(['--install', '--index-url', mirror]), 0)
        calls = [c.args[0] for c in self.run.call_args_list if 'pip' in c.args[0]]
        self.assertEqual(calls[0][calls[0].index('--index-url') + 1], mirror)
        self.assertIn('--isolated', calls[0])
        self.assertNotIn(mirror, self.output.getvalue())
        self.assertFalse(any(mirror in c.args[0] for c in self.run.call_args_list if 'pip' not in c.args[0]))

    def test_help_success_with_missing_tool_is_partial_not_check_pass(self):
        self.owned()
        with patch.object(b.shutil, 'which', side_effect=lambda name: None if name == 'opencli' else '/tools/' + name + ('.exe' if sys.platform == 'win32' else '')):
            self.assertEqual(b.main(['--check']), 1)
        self.assertIn('help_ok:', self.output.getvalue())
        self.assertNotIn('smoke_passed:', self.output.getvalue())
        self.assertIn('partial_help_ok:', self.output.getvalue())

    def test_windows_interpreter_layout(self):
        self.assertEqual(b.venv_python(Path('local'), windows=True), Path('local/Scripts/python.exe'))
        self.assertEqual(b.venv_python(Path('local'), windows=False), Path('local/bin/python'))


if __name__ == '__main__':
    unittest.main()
