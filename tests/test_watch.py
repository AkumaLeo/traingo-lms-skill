"""Synthetic fixtures only. No live LMS or browser learning records are used."""
import copy
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('traingo_watch', ROOT / 'scripts/traingo_watch.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def config():
    return w.validate_config({'session': 'explicit-test-binding', 'courses': [
        {'title': 'Synthetic course', 'url': 'https://example.invalid/player/one'}]})


def snap():
    return {'url': 'https://example.invalid/player/one', 'titles': ['Synthetic course'],
            'kind': 'course', 'dialog': 'none', 'total': 20, 'countdown': 60,
            'chapters': [{'title': 'Synthetic chapter A', 'percent': 100, 'current': True},
                         {'title': 'Synthetic chapter B', 'percent': 0, 'current': False}]}


class Fake:
    """Explicit synthetic adapter for offline integration tests."""
    def __init__(self, snapshots):
        self.snapshots = iter(snapshots)
        self.actions = []
    def inspect(self, target):
        value = next(self.snapshots)
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)
    def act(self, target, action):
        self.actions.append(action)
        return {'acted': True}


class WatchTests(unittest.TestCase):
    def test_config(self):
        self.assertEqual(config()['poll_seconds'], 30)
        for change in [{'courses': []}, {'session': ''}, {'poll_seconds': 1},
                       {'max_runtime': 0}, {'failure_limit': 0}, {'surprise': True}]:
            value = dict(config(), **change)
            with self.subTest(change=change), self.assertRaises(w.SafeError):
                w.validate_config(value)
        for url in ['http://example.invalid/a', 'https://u:p@example.invalid/a',
                    'https://example.invalid/a#fragment']:
            value = config(); value['courses'][0]['url'] = url
            with self.assertRaises(w.SafeError): w.validate_config(value)

    def test_wrong_identity(self):
        for change in [{'url': 'https://evil.invalid/player/one'},
                       {'url': 'https://example.invalid/player/two'},
                       {'titles': []}, {'titles': ['Other course']},
                       {'titles': ['Synthetic course', 'Synthetic course']},
                       {'kind': 'exam'}, {'dialog': 'unknown'}, {'dialog': 'identity'}, {'dialog': 'concurrent'}]:
            with self.subTest(change=change), self.assertRaises(w.SafeError):
                w.validate_snapshot(dict(snap(), **change), config()['courses'][0])

    def test_percentages(self):
        for value in [-1, 101, '100', None, True, float('nan')]:
            s = snap(); s['chapters'][0]['percent'] = value
            with self.subTest(value=value), self.assertRaises(w.SafeError):
                w.validate_snapshot(s, config()['courses'][0])

    def test_normalization(self):
        s = snap(); s['titles'] = ['  Synthetic\u00a0course\n']
        self.assertEqual(w.validate_snapshot(s, config()['courses'][0])['titles'], ['Synthetic course'])

    def test_decisions(self):
        s = snap()
        self.assertEqual(w.decide(s), {'kind': 'chapter', 'index': 1})
        s['chapters'][0]['percent'] = 99
        self.assertEqual(w.decide(s), {'kind': 'wait'})
        s['countdown'] = 0
        self.assertEqual(w.decide(s), {'kind': 'wait'})
        s['dialog'] = 'continue'
        self.assertEqual(w.decide(s), {'kind': 'continue'})
        s['dialog'] = 'concurrent'
        with self.assertRaises(w.SafeError): w.decide(s)

    def test_completion_requires_all_evidence(self):
        s = snap(); s['total'] = 100
        self.assertNotEqual(w.decide(s)['kind'], 'complete')
        for c in s['chapters']: c['percent'] = 100
        self.assertEqual(w.decide(s)['kind'], 'complete')
        s['total'] = 99
        self.assertNotEqual(w.decide(s)['kind'], 'complete')

    def test_readonly_and_safe_status(self):
        with tempfile.TemporaryDirectory() as d:
            s = snap(); s['raw'] = 'SECRET'; s['account'] = 'SECRET'
            a = Fake([s]); m = w.Monitor(config(), pathlib.Path(d), a, False)
            self.assertEqual(m.tick(), 'inspected')
            self.assertEqual(a.actions, [])
            data = (pathlib.Path(d) / 'status.json').read_text()
            for forbidden in ['SECRET', 'https:', 'account', 'raw']:
                self.assertNotIn(forbidden, data)
            self.assertFalse((pathlib.Path(d) / 'ledger.json').exists())

    def test_navigation_ledger_and_invalidation(self):
        with tempfile.TemporaryDirectory() as d:
            c = config(); c['courses'].append({'title': 'Synthetic second', 'url': 'https://example.invalid/player/two'})
            c = w.validate_config(c)
            s = snap(); s['total'] = 100
            for chapter in s['chapters']: chapter['percent'] = 100
            a = Fake([s]); m = w.Monitor(c, pathlib.Path(d), a, True)
            self.assertEqual(m.tick(), 'navigating')
            self.assertEqual(a.actions[0], {'kind': 'navigate', 'url': c['courses'][1]['url']})
            ledger = json.loads((pathlib.Path(d) / 'ledger.json').read_text())
            self.assertEqual(len(ledger['completed']), 1)
            c['courses'][0]['title'] = 'Changed synthetic course'
            m = w.Monitor(c, pathlib.Path(d), Fake([]), True)
            self.assertEqual(m.completed, [])
            self.assertEqual(m.index, 0)

    def test_stall_and_failures(self):
        with tempfile.TemporaryDirectory() as d:
            c = config(); c['stall_limit'] = 2; c['failure_limit'] = 2
            s = snap(); s['chapters'][0]['percent'] = 20
            a = Fake([s, s, s]); m = w.Monitor(c, pathlib.Path(d), a, True)
            self.assertEqual([m.tick(), m.tick(), m.tick()], ['waiting', 'waiting', 'stalled'])
        with tempfile.TemporaryDirectory() as d:
            a = Fake([w.BrowserError('private response'), w.BrowserError('private response')])
            m = w.Monitor(c, pathlib.Path(d), a, True)
            self.assertEqual([m.tick(), m.tick()], ['retry', 'failed'])
            self.assertNotIn('private response', (pathlib.Path(d) / 'status.json').read_text())

    def test_positive_evolution_only(self):
        with tempfile.TemporaryDirectory() as d:
            c = config(); c['stall_limit'] = 2
            s = snap(); s['chapters'][0]['percent'] = 20
            t = copy.deepcopy(s); t['countdown'] = 59
            u = copy.deepcopy(t); u['countdown'] = 65
            m = w.Monitor(c, pathlib.Path(d), Fake([s,t,u,u]), True)
            self.assertEqual([m.tick() for _ in range(4)], ['waiting','waiting','waiting','stalled'])

    def test_lock_and_stop(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d)
            with w.Lock(p):
                with self.assertRaises(w.SafeError):
                    with w.Lock(p): pass
            (p/'STOP').touch()
            m = w.Monitor(config(), p, Fake([]), True)
            self.assertEqual(m.tick(), 'stopped')

    def test_adapter_envelope_and_no_shell(self):
        c = config(); c['profile'] = 'synthetic-profile'; c['executable'] = 'opencli'
        a = w.OpenCLI(c)
        response = mock.Mock(returncode=0, stdout=json.dumps({'ok': True, 'data': snap()}))
        with mock.patch.object(w.subprocess, 'run', return_value=response) as run:
            self.assertEqual(a.inspect(c['courses'][0]), snap())
            argv = run.call_args[0][0]
            self.assertIsInstance(argv, list)
            self.assertIn('--session', argv); self.assertIn('--profile', argv)
            self.assertFalse(run.call_args[1].get('shell', False))
        response.stdout = '{"ok":false,"error":{"message":"SECRET"}}'
        with mock.patch.object(w.subprocess, 'run', return_value=response), self.assertRaises(w.BrowserError):
            a.inspect(c['courses'][0])

    def test_action_failures_are_bounded_without_duplicate_ledger(self):
        class Broken(Fake):
            def act(self, target, action):
                raise w.BrowserError('sensitive browser failure')
        with tempfile.TemporaryDirectory() as d:
            c = config(); c['failure_limit'] = 2
            c['courses'].append({'title': 'Synthetic second', 'url': 'https://example.invalid/player/two'})
            s = snap(); s['total'] = 100
            for chapter in s['chapters']: chapter['percent'] = 100
            m = w.Monitor(c, pathlib.Path(d), Broken([s,s]), True)
            self.assertEqual([m.tick(), m.tick()], ['retry', 'failed'])
            self.assertEqual(m.completed, [])

    def test_continue_requires_opt_in_and_concurrent_stops(self):
        for dialog, state, authorize, actions in [('continue','authorization_required',False,0),
                ('continue','acted',True,1), ('concurrent','safety_stop',True,0),
                ('unknown','safety_stop',True,0), ('identity','safety_stop',True,0)]:
            with self.subTest(dialog=dialog, authorize=authorize), tempfile.TemporaryDirectory() as d:
                c = config(); c['allow_continue'] = authorize
                a = Fake([dict(snap(), dialog=dialog)])
                self.assertEqual(w.Monitor(c, pathlib.Path(d), a, True).tick(), state)
                self.assertEqual(len(a.actions), actions)

    def test_stop_after_inspect_prevents_action(self):
        with tempfile.TemporaryDirectory() as d:
            class Stopping(Fake):
                def inspect(self, target):
                    (pathlib.Path(d)/'STOP').touch()
                    return snap()
            a = Stopping([])
            self.assertEqual(w.Monitor(config(), pathlib.Path(d), a, True).tick(), 'stopped')
            self.assertEqual(a.actions, [])

    def test_cli_safe_modes_with_explicit_synthetic_executable(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d)
            executable = p/'synthetic-opencli'
            executable.write_text('#!' + sys.executable + '\nimport json\nprint(' + repr(json.dumps({'ok': True, 'data': snap()})) + ')\n')
            executable.chmod(0o700)
            c = config(); c['executable'] = str(executable)
            cfg = p/'test-config.json'; cfg.write_text(json.dumps(c))
            for flag in [[], ['--once'], ['--read-only'], ['--dry-run']]:
                with self.subTest(flag=flag):
                    result = subprocess.run([sys.executable, str(ROOT/'scripts/traingo_watch.py'),
                        '--config', str(cfg), '--state-dir', str(p/'state')] + flag,
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)['state'], 'inspected')
                    self.assertFalse((p/'state'/'ledger.json').exists())

    @unittest.skipUnless(shutil.which('node'), 'Node required for synthetic DOM adapter tests')
    def test_javascript_synthetic_dom_and_scoped_actions(self):
        harness = r'''
const fs = require('fs'), vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
// All objects below are synthetic test fixtures, NOT browser/course responses.
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
const output = cases.map(test => {
  let clicks = 0, navigated = null;
  const element = (text, on=false) => ({textContent:text, innerText:text,
    getClientRects:()=>[{}], classList:{contains:name=>on && name==='on'},
    contains:()=>false, querySelector:()=>null, querySelectorAll:()=>[],
    click:()=>{clicks++;}});
  const title = element(test.wrongTitle ? 'Wrong course' : 'Synthetic course');
  const chapters = [element('Synthetic chapter A 进度:'+(test.percent===undefined?100:test.percent)+'%',true),
                    element((test.chapterBTitle||'Synthetic chapter B')+' 进度:'+(test.complete?100:0)+'%')];
  const button = element('确 定');
  const modal = element(['normal','warm'].includes(test.modal) ? (test.modal==='warm'?'温馨提示':'提示')+' 请确认您是否还在学习 确 定' : 'Unknown dialog 确 定');
  modal.querySelectorAll=()=>[button];
  const body = '总进度 '+(test.complete?100:20)+'% 再学 01:00 '+
    (test.concurrent?'系统禁止同时学习多个课程 继续学习当前内容':'');
  const location = {href:test.wrongUrl?'https://evil.invalid/player/one':'https://example.invalid/player/one',
                    assign:url=>{navigated=url;}};
  const document = {body:{innerText:body}, querySelectorAll:selector=>{
    if(selector==='TITLE_SELECTOR')return [title];
    if(selector==='ul.chapter li')return chapters;
    if(selector.startsWith('[role="dialog"]'))return test.modal?[modal]:[];
    if(selector.startsWith('input[type="password"]'))return test.identity?[element('')]:[];
    if(selector.startsWith('.exam-paper'))return test.exam?[element('')]:[];
    return [];
  }};
  const fn = vm.runInNewContext('('+source+')', {document,location,
       getComputedStyle:()=>({visibility:'visible',display:'block'})});
  const result = fn({target:{title:'Synthetic course',url:'https://example.invalid/player/one'},
    titleSelector:'TITLE_SELECTOR', allowContinue:test.authorize===true,
    allowedCourses:[{title:'Second synthetic course',url:'https://example.invalid/player/two'}],
    action:{...(test.action||{kind:'inspect'}),expected_chapters:[
      {title:'Synthetic chapter A',current:true,exam:false},
      {title:'Synthetic chapter B',current:false,exam:false}]}});
  return {result,clicks,navigated};
});
process.stdout.write(JSON.stringify(output));
'''
        cases = [
            {}, {'action': {'kind':'chapter','index':1}},
            {'percent':99,'action':{'kind':'chapter','index':1}},
            {'wrongTitle':True,'action':{'kind':'chapter','index':1}},
            {'wrongUrl':True,'action':{'kind':'chapter','index':1}},
            {'exam':True,'action':{'kind':'chapter','index':1}},
            {'modal':'normal','authorize':True,'action':{'kind':'continue'}},
            {'modal':'normal','authorize':False,'action':{'kind':'continue'}},
            {'modal':'unknown','authorize':True,'action':{'kind':'continue'}},
            {'concurrent':True,'authorize':True,'action':{'kind':'continue'}},
            {'identity':True,'authorize':True,'action':{'kind':'continue'}},
            {'complete':True,'action':{'kind':'navigate','url':'https://example.invalid/player/two'}},
            {'complete':True,'action':{'kind':'navigate','url':'https://evil.invalid/'}},
            {'action':{'kind':'navigate','url':'https://example.invalid/player/two'}},
            {'chapterBTitle':'Different chapter','action':{'kind':'chapter','index':1}},
            {'chapterBTitle':'在线考试','action':{'kind':'chapter','index':1}},
            {'modal':'warm','authorize':True,'action':{'kind':'continue'}},
            {'chapterBTitle':'测验','complete':True,'action':{'kind':'navigate','url':'https://example.invalid/player/two'}}]
        process = subprocess.run(['node','-e',harness,str(ROOT/'scripts/traingo_player.js')],
            input=json.dumps(cases), text=True, capture_output=True, timeout=10)
        self.assertEqual(process.returncode,0,process.stderr)
        values = json.loads(process.stdout)
        self.assertEqual(values[0]['result']['total'],20)
        self.assertEqual(values[0]['result']['countdown'],60)
        self.assertEqual(values[0]['result']['chapters'][0]['title'],'Synthetic chapter A')
        self.assertEqual([v['clicks'] for v in values], [0,1,0,0,0,0,1,0,0,0,0,0,0,0,0,0,1,0])
        self.assertEqual([i for i,v in enumerate(values) if v['navigated']], [11,17])
        for i in [2,3,4,5,7,8,9,10,12,13]:
            self.assertFalse(values[i]['result']['acted'])

    def test_cli_bounded_run_with_synthetic_executable(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d); executable = p/'synthetic-opencli'
            s = snap(); s['chapters'][0]['percent'] = 20
            executable.write_text('#!' + sys.executable + '\nprint(' + repr(json.dumps({'ok': True, 'data': s})) + ')\n')
            executable.chmod(0o700)
            c = config(); c.update(executable=str(executable), max_runtime=1)
            cfg = p/'synthetic-config.json'; cfg.write_text(json.dumps(c))
            result = subprocess.run([sys.executable, str(ROOT/'scripts/traingo_watch.py'),
                '--config',str(cfg),'--state-dir',str(p/'state'),'--run'],
                text=True,capture_output=True,timeout=5)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertEqual(json.loads(result.stdout)['state'],'runtime_limit')
            self.assertEqual(json.loads((p/'state'/'status.json').read_text())['state'],'runtime_limit')
            self.assertFalse((p/'state'/'watch.lock').exists())

    def test_readonly_does_not_skip_live_inspection_for_completed_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            s = snap(); s['total'] = 100
            for chapter in s['chapters']: chapter['percent'] = 100
            self.assertEqual(w.Monitor(config(), pathlib.Path(d), Fake([s]), True).tick(), 'complete')
            a = Fake([dict(s, titles=['Wrong course'])])
            self.assertEqual(w.Monitor(config(), pathlib.Path(d), a, False).tick(), 'safety_stop')

    def test_bounded_loop(self):
        with tempfile.TemporaryDirectory() as d:
            c = config(); c['max_runtime'] = 31
            s = snap(); s['chapters'][0]['percent'] = 0
            m = w.Monitor(c, pathlib.Path(d), Fake([s,s]), True)
            clock = [0.0]
            def sleep(n): clock[0] += n
            with mock.patch.object(w.time, 'monotonic', side_effect=lambda: clock[0]), mock.patch.object(w.time, 'sleep', side_effect=sleep):
                self.assertEqual(w.run_loop(m, False), 'runtime_limit')
            self.assertEqual(clock[0], 31)


if __name__ == '__main__':
    unittest.main()
