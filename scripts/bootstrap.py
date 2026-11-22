#!/usr/bin/env python3
"""Local deployment preflight, not skill registration or browser configuration.

Default is read-only. --install consents ONLY to a repository-local virtualenv
and pip requirements installation (network possible). --check runs script help,
never a browser/course command. Child output and exception details are withheld.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
MARKER = '.traingo-bootstrap-owner'
MARKER_VALUE = 'traingo-lms-bootstrap-v1\n'
ENV_CHECK = (
    "import sys; from pathlib import Path; "
    "assert sys.version_info >= (3, 9); "
    "assert sys.prefix != sys.base_prefix; "
    "assert Path(sys.prefix).resolve() == Path('.venv').resolve()"
)
DEPENDENCY_CHECK = (
    "import importlib.metadata as m; import fitz; "
    "v = tuple(int(n) for n in m.version('PyMuPDF').split('.')[:2]); "
    "assert (1, 24) <= v < (2, 0)"
)


def venv_python(directory, windows=None):
    if windows is None:
        windows = sys.platform == 'win32'
    return directory / ('Scripts/python.exe' if windows else 'bin/python')


def command(argv, timeout=15):
    """Only fixed probes/install argv; never expose subprocess output or errors."""
    try:
        environment = os.environ.copy()
        # pip/requests must not consult user pip configuration or .netrc.
        environment.update(PIP_CONFIG_FILE=os.devnull, NETRC=os.devnull)
        return subprocess.run(
            argv, cwd=str(ROOT), stdin=subprocess.DEVNULL, env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout, shell=False, check=False,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def owned_environment(directory):
    """Do not adopt an existing user venv, symlink or partial failed creation."""
    try:
        if directory.is_symlink() or not directory.is_dir():
            return False
        marker = directory / MARKER
        config = directory / 'pyvenv.cfg'
        executable = venv_python(directory)
        return (not marker.is_symlink() and marker.is_file()
                and marker.stat().st_size == len(MARKER_VALUE)
                and marker.read_text(encoding='utf-8') == MARKER_VALUE
                and not config.is_symlink() and config.is_file()
                and not executable.parent.is_symlink() and executable.is_file())
    except (OSError, UnicodeError):
        return False


def prepare_environment(install):
    directory = ROOT / '.venv'
    if directory.exists() or directory.is_symlink():
        if not owned_environment(directory):
            print('blocked: unknown .venv; inspect/move it manually or use a fresh checkout; nothing overwritten')
            return None
    elif not install:
        print('missing: .venv; run scripts/bootstrap.py --install after reviewing the repository')
        return None
    else:
        try:
            # Exclusive reservation, never pass an unknown existing directory to venv.
            directory.mkdir()
            venv.EnvBuilder(with_pip=False).create(str(directory))
            # Keep ensurepip's subprocess under our timeout/output policy too.
            if not command([str(venv_python(directory)), '-I', '-m', 'ensurepip', '--default-pip'], timeout=120):
                print('failed: local ensurepip; inspect partial .venv manually or use a fresh checkout')
                return None
            with (directory / MARKER).open('x', encoding='utf-8', newline='\n') as marker:
                marker.write(MARKER_VALUE)
        except (OSError, subprocess.SubprocessError):
            print('failed: local venv creation; inspect partial .venv manually; it is not removed or adopted')
            return None
    python = str(venv_python(directory))
    if not command([python, '-I', '-B', '-c', ENV_CHECK]):
        print('failed: .venv interpreter validation; use Python 3.9+ and a fresh checkout')
        return None
    if install:
        # Explicit opt-in only; isolated ignores pip config/environment settings.
        # No global pip, no cache, no package/tool/extension global installation.
        if not command([python, '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check',
                        'install', '--no-input', '--no-cache-dir', '--retries', '1', '--timeout', '15',
                        '-r', str(ROOT / 'requirements.txt')],
                       timeout=300):
            print('failed: local pip install; check network/Python package support, then retry --install; raw output withheld')
            return None
    if not command([python, '-I', '-B', '-c', DEPENDENCY_CHECK]):
        print('missing: compatible PyMuPDF in .venv; review requirements.txt then retry --install')
        return None
    print('local_dependencies_ready: owned .venv interpreter and PyMuPDF verified; not a registered skill')
    return python


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', help='consent to local .venv creation and pip install; network possible')
    parser.add_argument('--check', action='store_true', help='also smoke-test both existing scripts with --help only')
    args = parser.parse_args(argv)
    print('privacy: fixed status only; no paths, child output, credentials or browser data reported; no report file written')
    if sys.version_info < (3, 9):
        print('missing: Python 3.9+; install/select it manually before retrying')
        return 1
    print('ok: Python 3.9+')
    tools_ok = True
    for name, hint in (
        ('node', 'install Node.js manually using its official instructions'),
        ('npm', 'install/select npm with Node.js manually'),
        ('opencli', 'install OpenCLI 2.x and Browser Bridge manually per upstream README'),
    ):
        executable = shutil.which(name)
        if executable is None or not command([executable, '--version']):
            print('missing_or_failed: ' + name + '; ' + hint + '; ensure it is on PATH')
            tools_ok = False
        else:
            print('ok: ' + name + ' --version; compatibility/browser connection not verified')
    python = prepare_environment(args.install)
    if python is None:
        return 1
    smoke_ok = True
    if args.check:
        for script in ('extract_course.py', 'traingo_watch.py'):
            if command([python, '-I', '-B', str(ROOT / 'scripts' / script), '--help']):
                print('help_ok: ' + script)
            else:
                print('help_failed: ' + script + '; inspect the local script/dependencies manually')
                smoke_ok = False
        if smoke_ok:
            print('smoke_passed: CLI help only; no browser, login, learning or course verification')
    else:
        print('not_checked: CLI smoke; run scripts/bootstrap.py --check')
    print('manual_boundary: upload/enable SKILL.md folder in host UI; Chrome/extension/binding and real-course validation remain separate')
    return 0 if tools_ok and smoke_ok else 1


if __name__ == '__main__':
    sys.exit(main())
