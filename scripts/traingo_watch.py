#!/usr/bin/env python3
"""DOM-only Traingo monitor. Inspect is default; --run opts into record-changing UI.

Bind a real, verified Browser Bridge tab to the configured OpenCLI session.
This tool never logs in, opens duplicate learning tabs, calls credit APIs, plays hidden media, or
answers exams. No external notifications. Status/ledger contain only whitelisted
course/chapter evidence. A stale lock requires human review before removal.
"""
import argparse
import contextlib
import hashlib
import json
import math
import os
import re
from pathlib import Path
import subprocess
import sys

# -I source execution omits the script directory; trust only this bundled sibling.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_argv import build_argv
import tempfile
import time
from urllib.parse import urlsplit


class SafeError(Exception):
    """Fail-closed condition; messages are fixed codes, not browser content."""


class BrowserError(SafeError):
    pass


def norm(value):
    if not isinstance(value, str):
        raise SafeError('invalid_text')
    value = ' '.join(value.split())
    if not value or len(value) > 300:
        raise SafeError('invalid_text')
    return value


def restricted(value):
    return bool(re.search(r"考试|测验|答题|试卷|问卷|exam|quiz|assessment|survey", value, re.I))


def validate_config(raw):
    defaults = dict(executable='opencli', profile=None, poll_seconds=30,
                    max_runtime=3600, failure_limit=3, stall_limit=10,
                    command_timeout=15, allow_continue=False,
                    title_selector='h1.course-title, .course-title h1, .course-name')
    if not isinstance(raw, dict) or set(raw) - (set(defaults) | {'courses', 'session'}):
        raise SafeError('invalid_config')
    c = dict(defaults, **raw)
    for key in ['session', 'executable', 'title_selector']:
        c[key] = norm(c.get(key))
    if c['profile'] is not None:
        c['profile'] = norm(c['profile'])
    if type(c['allow_continue']) is not bool:
        raise SafeError('invalid_config')
    for key, low, high in [('poll_seconds', 30, 300), ('max_runtime', 1, 86400),
                           ('failure_limit', 1, 10), ('stall_limit', 1, 120),
                           ('command_timeout', 1, 60)]:
        if type(c[key]) is not int or not low <= c[key] <= high:
            raise SafeError('invalid_config')
    if not isinstance(c.get('courses'), list) or not c['courses']:
        raise SafeError('invalid_courses')
    courses = []
    for target in c['courses']:
        if not isinstance(target, dict) or set(target) != {'title', 'url'}:
            raise SafeError('invalid_course')
        title = norm(target['title'])
        if restricted(title) or re.search(r'https?://', title, re.I):
            raise SafeError('not_course')
        url = target['url']
        if not isinstance(url, str) or any(x.isspace() for x in url):
            raise SafeError('invalid_url')
        try:
            u = urlsplit(url)
            if u.scheme != 'https' or not u.hostname or u.username or u.password or u.fragment:
                raise ValueError()
            _ = u.port
            if re.search(r'/(?:exam|quiz|assessment|survey)(?:/|$)', u.path, re.I):
                raise ValueError()
        except ValueError:
            raise SafeError('invalid_url') from None
        if any(t['url'] == url or t['title'] == title for t in courses):
            raise SafeError('ambiguous_allowlist')
        courses.append(dict(title=title, url=url))
    c['courses'] = courses
    return c


def percent(value):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 100:
        raise SafeError('invalid_progress')
    return value


def validate_snapshot(s, target):
    if not isinstance(s, dict) or s.get('url') != target['url']:
        raise SafeError('wrong_target')
    titles = s.get('titles')
    if not isinstance(titles, list) or len(titles) != 1 or norm(titles[0]) != target['title']:
        raise SafeError('ambiguous_identity')
    if s.get('kind') != 'course':
        raise SafeError('not_course')
    if s.get('dialog') not in ('none', 'continue'):
        raise SafeError('blocked_dialog')
    total = percent(s.get('total'))
    countdown = s.get('countdown')
    if countdown is not None and (type(countdown) is not int or not 0 <= countdown <= 86400):
        raise SafeError('invalid_countdown')
    chapters = s.get('chapters')
    if not isinstance(chapters, list) or not chapters or len(chapters) > 1000:
        raise SafeError('missing_chapters')
    clean = []
    for item in chapters:
        if not isinstance(item, dict) or type(item.get('current')) is not bool:
            raise SafeError('invalid_chapter')
        title = norm(item.get('title'))
        if re.search(r'https?://', title, re.I):
            raise SafeError('invalid_text')
        if type(item.get('exam', False)) is not bool:
            raise SafeError('invalid_chapter')
        blocked = item.get('exam', False) or restricted(title)
        if blocked and item['current']:
            raise SafeError('not_course')
        progress = item.get('percent')
        clean.append(dict(title=title, percent=None if blocked and progress is None else percent(progress),
                          current=item['current'], exam=blocked))
    if sum(x['current'] for x in clean) != 1:
        raise SafeError('ambiguous_chapter')
    return dict(url=target['url'], titles=[target['title']], kind='course',
                dialog=s['dialog'], total=total, countdown=countdown, chapters=clean)


def decide(s):
    if s['dialog'] == 'continue':
        return {'kind': 'continue'}
    if s['dialog'] != 'none':
        raise SafeError('blocked_dialog')
    chapters = s['chapters']
    blocked = lambda x: x.get('exam', False) or restricted(x['title'])
    online = [x for x in chapters if not blocked(x)]
    if not online or any(x['current'] and blocked(x) for x in chapters):
        raise SafeError('not_course')
    if all(x['percent'] == 100 for x in online) and (s['total'] == 100 or any(blocked(x) for x in chapters)):
        return {'kind': 'complete'}
    index = next(i for i, x in enumerate(chapters) if x['current'])
    if chapters[index]['percent'] == 100:
        remaining = [i for i, x in enumerate(chapters) if not blocked(x) and x['percent'] < 100]
        if remaining:
            return {'kind': 'chapter', 'index': remaining[0]}
    return {'kind': 'wait'}


def fingerprint(config):
    # Any config change invalidates all resumable completion evidence.
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, sort_keys=True)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        with contextlib.suppress(FileNotFoundError): os.unlink(name)


class Lock:
    """Portable mkdir lock. Never auto-break a possibly live/stale owner."""
    def __init__(self, directory):
        self.path = Path(directory) / 'watch.lock'
    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try: self.path.mkdir()
        except FileExistsError: raise SafeError('locked') from None
        return self
    def __exit__(self, *args):
        self.path.rmdir()


class OpenCLI:
    def __init__(self, config):
        self.config = config
        self.deadline = None
        self.script = Path(__file__).with_name('traingo_player.js').read_text(encoding='utf-8')
    def call(self, target, action):
        c = self.config
        payload = dict(target=target, action=action, titleSelector=c['title_selector'],
                       allowContinue=c['allow_continue'], allowedCourses=c['courses'])
        expression = '(' + self.script + ')(' + json.dumps(payload, ensure_ascii=True) + ')'
        argv = [c['executable'], 'browser', 'eval', '--session', c['session']]
        if c['profile']: argv += ['--profile', c['profile']]
        argv.append(expression)
        budget = c['command_timeout']
        if self.deadline is not None:
            budget = min(budget, self.deadline - time.monotonic())
        if budget <= 0: raise BrowserError('runtime_limit')
        try:
            result = subprocess.run(build_argv(argv[0], argv[1:]), capture_output=True, text=True, encoding='utf-8', timeout=budget,
                                    check=False, shell=False)
            envelope = json.loads(result.stdout)
            if result.returncode or not isinstance(envelope, dict) or envelope.get('ok') is not True:
                raise BrowserError('browser_failure')
            data = envelope['data']
            if not isinstance(data, dict): raise BrowserError('browser_shape')
            return data
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            # Never relay stdout/stderr, invocation payload, or browser error strings.
            raise BrowserError('browser_failure') from None
    def inspect(self, target):
        return self.call(target, {'kind': 'inspect'})
    def act(self, target, action):
        result = self.call(target, action)
        if result.get('acted') is not True:
            raise SafeError('action_refused')
        return result


class Monitor:
    def __init__(self, config, directory, adapter, run=False):
        self.config = validate_config(config)
        self.directory = Path(directory)
        self.adapter = adapter
        self.run = run
        self.digest = fingerprint(self.config)
        self.index = 0; self.completed = []; self.previous = None
        self.failures = 0; self.stalls = 0
        path = self.directory / 'ledger.json'
        if path.exists():
            try:
                ledger = json.loads(path.read_text(encoding='utf-8'))
                n = ledger['next_index']
                expected = [dict(index=i, title=t['title']) for i,t in enumerate(self.config['courses'][:n])]
                if (ledger['config_digest'] == self.digest and type(n) is int and
                        0 <= n <= len(self.config['courses']) and ledger['completed'] == expected):
                    self.index = n; self.completed = expected
            except (OSError, ValueError, KeyError, TypeError):
                raise SafeError('invalid_ledger') from None
    def status(self, state, snapshot=None, error_code=None):
        if state in ('inspected', 'acted', 'waiting', 'navigating', 'complete'):
            self.failures = 0
        data = dict(schema=1, state=state, mode='run' if self.run else 'read-only',
                    course_index=self.index, completed_count=len(self.completed),
                    failure_count=self.failures, stall_count=self.stalls,
                    updated_at=int(time.time()), config_digest=self.digest)
        if error_code:
            data['error_code'] = error_code
        if snapshot:
            data.update(course=snapshot['titles'][0], total=snapshot['total'],
                        countdown=snapshot['countdown'], chapters=snapshot['chapters'])
        atomic_json(self.directory/'status.json', data)
        return state
    def checkpoint(self):
        atomic_json(self.directory/'ledger.json', dict(schema=1, config_digest=self.digest,
                    next_index=self.index, completed=self.completed))
    def tick(self):
        if (self.directory/'STOP').exists(): return self.status('stopped')
        target = self.config['courses'][min(self.index, len(self.config['courses']) - 1)]
        try:
            s = validate_snapshot(self.adapter.inspect(target), target)
            action = decide(s)
            if not self.run: return self.status('inspected', s)
            if (self.directory/'STOP').exists(): return self.status('stopped')
            if self.index >= len(self.config['courses']):
                if action['kind'] != 'complete': raise SafeError('completion_changed')
                return self.status('complete', s)
            if self.previous is not None:
                p = self.previous
                same_chapters = [x['title'] for x in s['chapters']] == [x['title'] for x in p['chapters']]
                if not same_chapters: raise SafeError('chapter_list_changed')
                positive = (s['total'] > p['total'] or
                            any(x['percent'] is not None and y['percent'] is not None and x['percent'] > y['percent']
                                for x,y in zip(s['chapters'],p['chapters'])) or
                            (s['countdown'] is not None and p['countdown'] is not None and
                             0 <= s['countdown'] < p['countdown']))
                self.stalls = 0 if positive else self.stalls + 1
            self.previous = s
            if self.stalls >= self.config['stall_limit']: return self.status('stalled', s)
            if action['kind'] == 'complete':
                # Completion ledger is written only after fresh DOM 100% evidence.
                next_index = self.index + 1
                if next_index < len(self.config['courses']):
                    self.adapter.act(target, dict(kind='navigate', url=self.config['courses'][next_index]['url']))
                self.completed.append(dict(index=self.index, title=target['title']))
                self.index = next_index
                self.checkpoint()
                self.previous = None; self.stalls = 0
                return self.status('navigating' if next_index < len(self.config['courses']) else 'complete')
            if action['kind'] == 'continue' and not self.config['allow_continue']:
                return self.status('authorization_required', s)
            if action['kind'] != 'wait':
                if action['kind'] == 'chapter':
                    action = dict(action, expected_chapters=[
                        {key: chapter[key] for key in ('title','current','exam')}
                        for chapter in s['chapters']])
                self.adapter.act(target, action)
                return self.status('acted', s)
            return self.status('waiting', s)
        except BrowserError:
            self.failures += 1
            return self.status('failed' if self.failures >= self.config['failure_limit'] else 'retry',
                               error_code='browser_failure')
        except SafeError as error:
            safe_codes = {'wrong_target', 'ambiguous_identity', 'not_course', 'blocked_dialog',
                          'invalid_progress', 'invalid_countdown', 'missing_chapters', 'invalid_chapter',
                          'ambiguous_chapter', 'invalid_text', 'chapter_list_changed', 'action_refused',
                          'completion_changed'}
            code = str(error) if str(error) in safe_codes else 'safety_violation'
            return self.status('safety_stop', error_code=code)


TERMINAL = {'complete','stopped','stalled','failed','safety_stop','authorization_required'}


def run_loop(monitor, once):
    deadline = time.monotonic() + monitor.config['max_runtime']
    monitor.adapter.deadline = deadline
    while time.monotonic() < deadline:
        state = monitor.tick()
        if once or state in TERMINAL: return state
        remaining = deadline - time.monotonic()
        if remaining <= 0: break
        time.sleep(min(monitor.config['poll_seconds'], remaining))
    return monitor.status('runtime_limit')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, help='JSON config; explicitly bound OpenCLI session required')
    parser.add_argument('--state-dir', type=Path, default=Path('.traingo-watch'), help='private local status/ledger/STOP/lock directory')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--run', action='store_true', help='opt in to normal learning UI actions; may alter learning records')
    modes.add_argument('--read-only', action='store_true', help='safe inspect (default); never clicks or navigates')
    modes.add_argument('--dry-run', action='store_true', help='alias for read-only inspect')
    parser.add_argument('--once', action='store_true', help='one observation (with --run, at most one UI action)')
    parser.add_argument('--self-test', action='store_true', help='run synthetic offline unittest fixtures; no browser access')
    args = parser.parse_args(argv)
    if args.self_test:
        return subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s',
                               str(Path(__file__).resolve().parents[1]/'tests'), '-p', 'test_watch.py', '-v'], shell=False).returncode
    if args.config is None: parser.error('--config is required unless --self-test is used')
    try:
        c = validate_config(json.loads(args.config.read_text(encoding='utf-8')))
        with Lock(args.state_dir):
            m = Monitor(c, args.state_dir, OpenCLI(c), args.run)
            state = run_loop(m, args.once or not args.run)
            print(json.dumps({'state': state, 'mode': 'run' if args.run else 'read-only'}))
            return 0 if state in ('inspected','complete','acted','waiting','navigating','stopped') else 1
    except KeyboardInterrupt:
        print('{"state":"interrupted"}')
        return 130
    except (SafeError, OSError, ValueError, TypeError):
        # Config/browser errors may contain secrets: fixed output only.
        print('{"state":"configuration_or_io_error"}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
