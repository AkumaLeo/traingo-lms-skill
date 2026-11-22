"""Portable synthetic OpenCLI launcher; never returns real browser data."""
import json
from pathlib import Path
import shutil
import sys


def launcher(directory, response):
    directory = Path(directory)
    if sys.platform == 'win32':
        # Exercise the supported npm layout, not an unexecutable POSIX shebang.
        if not shutil.which('node.exe'):
            raise AssertionError('Windows CLI integration fixtures require project dependency node.exe on PATH')
        shim = directory / 'opencli.cmd'
        shim.write_bytes(b'@rem synthetic placeholder; must never execute\r\n')
        package = directory / 'node_modules' / '@jackwener' / 'opencli'
        package.mkdir(parents=True)
        (package / 'package.json').write_text(json.dumps({
            'name': '@jackwener/opencli', 'bin': {'opencli': 'fixture.js'}}), encoding='utf-8')
        (package / 'fixture.js').write_text('process.stdout.write(' + json.dumps(json.dumps(response)) + ');', encoding='utf-8')
        return shim
    executable = directory / 'synthetic-opencli'
    executable.write_text('#!' + sys.executable + '\nprint(' + repr(json.dumps(response)) + ')\n', encoding='utf-8')
    executable.chmod(0o700)
    return executable
