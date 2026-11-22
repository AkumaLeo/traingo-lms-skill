"""Shell-free launch argv for native tools and known Windows npm layouts.

Trust boundary: the operator supplies PATH/executable and installed packages.
Metadata validation is layout validation, NOT a package signature/security audit.
Never read, interpret or execute batch shim contents. Unknown layouts fail closed.
"""
import json
import ntpath
from pathlib import Path
import shutil
import sys


def build_argv(executable, arguments, windows=None):
    if windows is None:
        windows = sys.platform == 'win32'
    executable = str(executable)
    arguments = list(arguments)
    if not windows:
        return [executable, *arguments]
    resolved = (shutil.which(executable) or executable) if not ntpath.dirname(executable) else executable
    shim = Path(resolved)
    suffix = shim.suffix.lower()
    if suffix not in ('.cmd', '.bat'):
        # Do not accidentally pass an extensionless npm batch launcher to Windows.
        if suffix != '.exe':
            raise ValueError('native_exe_or_supported_npm_cmd_required')
        return [str(shim), *arguments]
    tool = shim.stem.lower()
    if suffix != '.cmd' or tool not in ('opencli', 'npm') or not shim.is_file():
        raise ValueError('unsupported_batch_launcher')
    package_name = '@jackwener/opencli' if tool == 'opencli' else 'npm'
    package = (shim.parent / 'node_modules' / package_name).resolve()
    try:
        metadata_path = package / 'package.json'
        if metadata_path.stat().st_size > 128 * 1024:
            raise ValueError()
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        if not isinstance(metadata, dict) or metadata.get('name') != package_name:
            raise ValueError()
        bins = metadata.get('bin')
        entry = bins.get(tool) if isinstance(bins, dict) else bins
        if (not isinstance(entry, str) or not entry or '\\' in entry or ':' in entry
                or any(ord(c) < 32 for c in entry) or ntpath.isabs(entry)
                or '..' in Path(entry).parts):
            raise ValueError()
        if tool == 'npm' and entry != 'bin/npm-cli.js':
            raise ValueError()
        target = (package / entry).resolve()
        target.relative_to(package)
        if not target.is_file() or target.suffix.lower() not in ('.js', '.mjs', '.cjs'):
            raise ValueError()
        # npm's standard shim prefers a sibling node.exe, otherwise PATH node.exe.
        node = shim.parent / 'node.exe'
        if not node.is_file():
            located = shutil.which('node.exe')
            if not located:
                raise ValueError()
            node = Path(located)
        if node.suffix.lower() != '.exe' or not node.is_file():
            raise ValueError()
        return [str(node), str(target), *arguments]
    except (OSError, UnicodeError, ValueError, TypeError):
        raise ValueError('npm_layout_unverified_use_official_install_and_node_exe') from None
