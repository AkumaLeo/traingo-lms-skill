"""Synthetic Windows layouts on any host; no Windows execution claim."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bootstrap as b


class PortabilityTests(unittest.TestCase):
    def builder(self):
        import safe_argv
        return safe_argv.build_argv

    def layout(self, root, tool='opencli', entry='dist/cli.js'):
        shim = root / (tool + '.cmd')
        shim.write_text('DO NOT PARSE OR EXECUTE THIS SHIM')
        node = root / 'node.exe'; node.touch()
        package = root / 'node_modules' / ('@jackwener/opencli' if tool == 'opencli' else 'npm')
        package.mkdir(parents=True)
        target = package / entry; target.parent.mkdir(parents=True, exist_ok=True); target.touch()
        metadata = {'name': '@jackwener/opencli' if tool == 'opencli' else 'npm',
                    'version': '2.0.2', 'bin': {tool: entry}}
        (package / 'package.json').write_text(json.dumps(metadata))
        return shim, node, package, target, metadata

    def test_native_and_posix_argv_preserved(self):
        for executable in ['opencli', '/opt/bin/opencli', 'native.exe']:
            self.assertEqual(self.builder()(executable, ['a & b', '"quoted"'], windows=False),
                             [executable, 'a & b', '"quoted"'])

    def test_windows_npm_shims_use_node_and_metadata_not_shell(self):
        for tool, entry in [('opencli', 'dist/cli.js'), ('npm', 'bin/npm-cli.js')]:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as d:
                shim, node, package, target, metadata = self.layout(Path(d), tool, entry)
                args = ['browser', 'eval', 'x & calc.exe | %PATH% " `']
                self.assertEqual(self.builder()(str(shim), args, windows=True),
                                 [str(node), str(target.resolve()), *args])

    def test_windows_rejects_unverified_layout_and_escape(self):
        for change in ['missing', 'wrong_name', 'escape', 'absolute', 'backslash', 'bad_bin', 'npm_wrong_entry']:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as d:
                tool = 'npm' if change == 'npm_wrong_entry' else 'opencli'
                shim, node, package, target, meta = self.layout(Path(d), tool)
                if change == 'missing': (package / 'package.json').unlink()
                else:
                    if change == 'wrong_name': meta['name'] = 'unrelated'
                    if change in ['escape', 'absolute', 'backslash', 'bad_bin']:
                        meta['bin'][tool] = {'escape': '../../outside.js', 'absolute': '/outside.js',
                                             'backslash': '..\\outside.js', 'bad_bin': 42}[change]
                    (package / 'package.json').write_text(json.dumps(meta))
                with self.assertRaises(ValueError): self.builder()(str(shim), ['--version'], windows=True)

    def test_windows_path_resolution_and_unknown_batch_refused(self):
        with tempfile.TemporaryDirectory() as d:
            shim, node, package, target, meta = self.layout(Path(d))
            with patch('shutil.which', return_value=str(shim)):
                self.assertEqual(self.builder()('opencli', ['--version'], windows=True), [str(node), str(target.resolve()), '--version'])
            with self.assertRaises(ValueError): self.builder()(str(Path(d) / 'other.cmd'), [], windows=True)

    def test_symlink_bin_escape_refused(self):
        with tempfile.TemporaryDirectory() as d:
            shim, node, package, target, meta = self.layout(Path(d))
            outside = Path(d) / 'outside.js'; outside.touch(); target.unlink()
            try: target.symlink_to(outside)
            except OSError as error:
                if sys.platform == 'win32' and getattr(error, 'winerror', None) == 1314:
                    self.skipTest('Windows symlink privilege unavailable')
                raise
            with self.assertRaises(ValueError): self.builder()(str(shim), [], windows=True)

    def test_mirror_validation_is_private_and_requires_install(self):
        invalid = ['http://mirror.invalid/simple', 'https://u:p@mirror.invalid/simple',
                   'https://mirror.invalid/?secret=x', 'https://mirror.invalid/#private',
                   'https://mirror.invalid/ a', 'https://mirror.invalid/\n',
                   'https://mirror.invalid/\x00', 'https://mirror.invalid/\x80',
                   'https://mirror.invalid/%80', 'https://mirror.invalid:bad/simple',
                   'https://mirror.invalid/?', 'https://mirror.invalid/#']
        for url in invalid:
            with self.subTest(url=url):
                # A regression must not turn malformed-argument tests into real probes/install.
                with patch.object(b.shutil, 'which', return_value=None), patch.object(b, 'prepare_environment', return_value=None), contextlib.redirect_stderr(io.StringIO()) as err:
                    with self.assertRaises(SystemExit) as exit:
                        b.main(['--install', '--index-url', url])
                    self.assertEqual(exit.exception.code, 2)
                    self.assertNotIn(url, err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            b.main(['--index-url', 'https://mirror.invalid/simple'])

    def test_all_callers_share_windows_builder_without_shell(self):
        import extract_course as extract
        import traingo_watch as watch
        import test_watch
        for module in [b, extract, watch]:
            with self.subTest(caller=module.__name__), tempfile.TemporaryDirectory() as d:
                shim, node, package, target, metadata = self.layout(Path(d))
                response = subprocess.CompletedProcess([], 0, json.dumps({'ok': True, 'data': {'synthetic': True}}))
                builder = self.builder()
                with patch.object(module, 'build_argv', side_effect=lambda exe, args: builder(exe, args, windows=True)) as build, patch.object(module.subprocess, 'run', return_value=response) as run:
                    if module is b:
                        self.assertTrue(b.command([str(shim), '--version']))
                    elif module is extract:
                        self.assertEqual(extract.Browser(str(shim)).evaluate('x & "quoted"'), {'synthetic': True})
                    else:
                        config = test_watch.config(); config['executable'] = str(shim)
                        watch.OpenCLI(config).inspect(config['courses'][0])
                    build.assert_called_once()
                    argv = run.call_args.args[0]
                    self.assertEqual(argv[:2], [str(node), str(target.resolve())])
                    self.assertNotIn(str(shim), argv)
                    self.assertIs(run.call_args.kwargs['shell'], False)
                    if module is not b:
                        self.assertEqual(run.call_args.kwargs.get('encoding'), 'utf-8')

    def test_real_node_executes_js_not_batch_and_preserves_arguments(self):
        import shutil
        node_source = shutil.which('node')
        self.assertIsNotNone(node_source, 'Project integration tests require Node.js')
        for tool, entry in [('opencli', 'dist/cli.js'), ('npm', 'bin/npm-cli.js')]:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as d:
                shim, node, package, target, metadata = self.layout(Path(d), tool, entry)
                shutil.copy2(node_source, node)
                target.write_text('process.stdout.write(JSON.stringify(process.argv.slice(2)));', encoding='utf-8')
                args = ['a & b | c', '%PATH%', '"quoted"', '中文', 'trailing\\']
                result = subprocess.run(self.builder()(str(shim), args, windows=True),
                                        text=True, encoding='utf-8', capture_output=True, shell=False, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), args)

    def test_windows_node_fallback_and_missing_node_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            shim, node, package, target, meta = self.layout(Path(d))
            node.unlink()
            fallback = Path(d) / 'runtime' / 'node.exe'
            fallback.parent.mkdir(); fallback.touch()
            with patch('shutil.which', return_value=str(fallback)):
                self.assertEqual(self.builder()(str(shim), [], windows=True)[:2], [str(fallback), str(target.resolve())])
            with patch('shutil.which', return_value=None), self.assertRaises(ValueError):
                self.builder()(str(shim), [], windows=True)

    def test_isolated_source_help_imports_shared_module(self):
        for name in ['bootstrap.py', 'extract_course.py', 'traingo_watch.py']:
            result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'scripts' / name), '--help'],
                                    text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__': unittest.main()
