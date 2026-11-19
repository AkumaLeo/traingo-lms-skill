"""Offline fixtures only: no real browser, credentials, or course material."""
import base64
import contextlib
import importlib.util
import io
import json
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('extract_course', ROOT / 'scripts/extract_course.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ExtractionTests(unittest.TestCase):
    def test_filename_preserves_exact_titles(self):
        self.assertEqual(m.safe_name('  示例：第一章 / A?  '), '  示例：第一章 _ A_  ')
        for value in ('', '.', '..'):
            with self.assertRaises(m.ExtractError):
                m.safe_name(value)

    def test_opencli_envelope_and_argv(self):
        result = subprocess.CompletedProcess([], 0, '{"ok":true,"data":{"pages":7}}', '')
        with patch.object(m.subprocess, 'run', return_value=result) as run:
            self.assertEqual(m.Browser('opencli', 'owned', 'profile', 12).evaluate('1'), {'pages': 7})
            self.assertEqual(run.call_args.args[0], ['opencli', 'browser', 'eval', '--session', 'owned', '--profile', 'profile', '1'])
            self.assertNotIn('shell', run.call_args.kwargs)

    def test_browser_errors_redacted(self):
        for result in (subprocess.CompletedProcess([], 1, '', 'https://example.invalid/private?secret=x'),
                       subprocess.CompletedProcess([], 0, '{"ok":false,"error":"secret"}', '')):
            with patch.object(m.subprocess, 'run', return_value=result):
                with self.assertRaises(m.ExtractError) as caught:
                    m.Browser().evaluate('1')
                self.assertNotIn('secret', str(caught.exception))

    def test_catalog_exact_target_and_fail_closed(self):
        meta = fixture()
        m.validate_metadata(meta, '示例课程', 0, '第一章')
        for key, value in [('pages', 0), ('source_origin', 'https://data.traingo.cn/private?x=1'), ('course', '考试')]:
            changed = dict(meta, **{key: value})
            with self.assertRaises(m.ExtractError):
                m.validate_metadata(changed, '示例课程', 0, '第一章')
        with self.assertRaises(m.ExtractError):
            m.validate_metadata(meta, '示例课程', 1, '第一章')

    def test_atomic_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'test.pdf'
            m.atomic_save(p, b'one')
            m.atomic_save(p, b'one')
            with self.assertRaises(m.ExtractError):
                m.atomic_save(p, b'two')
            self.assertEqual(p.read_bytes(), b'one')
            m.atomic_save(p, b'two', overwrite=True)
            self.assertEqual(p.read_bytes(), b'two')
            self.assertEqual([x.name for x in Path(d).iterdir()], ['test.pdf'])

    def test_pdf_validation_actual_generated_pdf(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('optional PyMuPDF unavailable')
        doc = fitz.open()
        doc.new_page()
        pdf = doc.tobytes()
        doc.close()
        self.assertEqual(m.validate_pdf(pdf, 1), 1)
        for payload, count in [(pdf, 2), (b'<html>login</html>', 1), (b'%PDF-fake', 1)]:
            with self.assertRaises(m.ExtractError):
                m.validate_pdf(payload, count)

    def test_download_chunks_and_cleanup(self):
        class FakeBrowser:
            def __init__(self):
                self.calls = []
            def call(self, action, **kw):
                self.calls.append((action, kw))
                if action == 'start':
                    return {'metadata': fixture(), 'size': 10}
                if action == 'chunk':
                    return {'offset': kw['offset'], 'data': base64.b64encode(b'%PDF-test!').decode()}
                return {'cleared': True}
        b = FakeBrowser()
        with patch.object(m, 'validate_pdf', return_value=7):
            with tempfile.TemporaryDirectory() as d:
                result = m.download(b, fixture(), Path(d), 1024, 1024, 10)
                self.assertEqual(result['viewer_pages'], 7)
                self.assertNotIn('?', json.dumps(result))
                self.assertEqual(result['filename'], '示例课程 — 第一章.pdf')
                self.assertTrue((Path(d) / result['filename']).exists())
        self.assertEqual(b.calls[-1][0], 'clear')
        self.assertNotIn('src', json.dumps(b.calls))

    def test_cleanup_on_bad_chunk(self):
        class Bad:
            def __init__(self): self.calls = []
            def call(self, action, **kw):
                self.calls.append(action)
                if action == 'start': return {'metadata': fixture(), 'size': 10}
                if action == 'chunk': return {'offset': 0, 'data': 'bad!!'}
                return {'cleared': True}
        b = Bad()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(m.ExtractError):
                m.download(b, fixture(), Path(d), 1024, 1024, 10)
            self.assertEqual(list(Path(d).iterdir()), [])
        self.assertEqual(b.calls[-1], 'clear')

    def test_cli_probe_does_not_fetch(self):
        stdout = io.StringIO()
        with patch.object(m.Browser, 'call', return_value=fixture()) as call, contextlib.redirect_stdout(stdout):
            self.assertEqual(m.main(['--probe', '--session', 'fixture-owned']), 0)
        self.assertEqual(call.call_args_list[0].args, ('probe',))
        self.assertEqual(call.call_count, 1)
        self.assertEqual(json.loads(stdout.getvalue()), fixture())

    def test_cli_download_real_pdf_with_mocked_transport(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('optional PyMuPDF unavailable')
        document = fitz.open()
        for _ in range(7):
            document.new_page()
        pdf = document.tobytes()
        document.close()
        actions = []

        def evaluate(expression):
            payload = json.loads(expression.rsplit(')(', 1)[1][:-1])
            actions.append(payload['action'])
            if payload['action'] == 'probe':
                return fixture()
            if payload['action'] == 'start':
                return {'metadata': fixture(), 'size': len(pdf)}
            if payload['action'] == 'chunk':
                offset, length = payload['offset'], payload['length']
                return {'offset': offset, 'data': base64.b64encode(pdf[offset:offset + length]).decode()}
            return {'cleared': True}

        with tempfile.TemporaryDirectory() as directory, patch.object(m.Browser, 'evaluate', side_effect=evaluate):
            args = ['--download', '--session', 'fixture-owned', '--output-dir', directory,
                    '--expect-course', '示例课程', '--chapter-index', '0', '--chapter-title', '第一章',
                    '--chunk-bytes', '128', '--max-bytes', '1048576', '--timeout', '20']
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(m.main(args), 0)
            manifest = json.loads(stdout.getvalue())
            self.assertEqual(manifest['pdf_pages'], 7)
            path = Path(directory) / manifest['filename']
            self.assertEqual(path.read_bytes(), pdf)
            self.assertEqual(json.loads(path.with_name(path.name + '.manifest.json').read_text()), manifest)
            self.assertEqual(actions[0], 'probe')
            self.assertEqual(actions[-1], 'clear')
            self.assertGreater(actions.count('chunk'), 1)
            self.assertNotIn('src', manifest)
            self.assertNotIn('?', json.dumps(manifest))
            # Idempotent identical files are accepted without --overwrite.
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(m.main(args), 0)

    def test_cli_invalid_limits_never_calls_browser(self):
        with patch.object(m.Browser, 'call') as call, contextlib.redirect_stderr(io.StringIO()):
            for args in (['--download'], ['--max-bytes', '104857601'], ['--chunk-bytes', '262145'], ['--timeout', '0']):
                with self.assertRaises(SystemExit) as caught:
                    m.main(args)
                self.assertEqual(caught.exception.code, 2)
        call.assert_not_called()

    def test_cleanup_when_fetch_fails(self):
        class Bad:
            def __init__(self): self.calls = []
            def call(self, action, **kwargs):
                self.calls.append(action)
                if action == 'start': raise m.ExtractError('browser_operation_failed')
                return {'cleared': True}
        browser = Bad()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(m.ExtractError):
                m.download(browser, fixture(), Path(directory), 1024, 1024, 10)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(browser.calls, ['start', 'clear'])

    def test_timeout_cleans_cache_and_restores_command_timeout(self):
        browser = m.Browser(timeout=45)
        with tempfile.TemporaryDirectory() as directory, patch.object(browser, 'call', side_effect=[
                {'metadata': fixture(), 'size': 10}, {'cleared': True}]) as call:
            with patch.object(m.time, 'monotonic', side_effect=[0, 0, 11]):
                with self.assertRaisesRegex(m.ExtractError, 'download_timeout'):
                    m.download(browser, fixture(), Path(directory), 1024, 1024, 10)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual([c.args[0] for c in call.call_args_list], ['start', 'clear'])
        self.assertEqual(browser.timeout, 45)

    def run_browser_fixture(self, scenario):
        if not shutil.which('node'):
            self.skipTest('Node.js optional for JS fixture tests')
        helper = (ROOT / 'scripts/traingo_document.js').read_text(encoding='utf-8')
        setup = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const el = (value, classes=[]) => ({innerText:value, textContent:value,
  getClientRects:()=>[{}], classList:{contains:c=>classes.includes(c)}, querySelectorAll:()=>[]});
const course = el('示例课程'), row = el('第一章\n进度：0%', ['on']);
row.querySelectorAll = () => [el('第一章')];
const visual = el('PDF viewer');
const photo = {type:{__name:'Photo'}, props:{src:'//data.traingo.cn/synthetic.pdf?signature=fixture-secret', pages:'7'},
  vnode:{el:visual}, subTree:{el:visual}};
const vnode = {type:photo.type, props:photo.props, el:visual, component:photo};
photo.subTree.children = [vnode]; // cycle exercises seen set and vnode/instance deduplication
const root = {subTree:{children:[vnode],dynamicChildren:[vnode]}};
const app = {__vue_app__:{_container:{_vnode:{component:root}}}};
const document = {querySelector:q=>q==='#app'?app:null,
 querySelectorAll:q=>q==='ul.chapter li'?[row]:q.includes('dialog')?[]:[course]};
const timers = [];
let mime='application/pdf', content=Buffer.from('%PDF-fixture'), declared=0;
const context = {window:{}, document, location:{protocol:'https:',hostname:'learn.traingo.cn',pathname:'/course/detail',href:'https://learn.traingo.cn/course/detail'},
 getComputedStyle:()=>({display:'block',visibility:'visible'}), URL, AbortController, Uint8Array,
 setTimeout:(f,ms)=>{timers.push(f);return timers.length;},clearTimeout:()=>{},
 btoa:s=>Buffer.from(s,'binary').toString('base64'), fetch:async()=>({ok:true,redirected:false,
 headers:{get:n=>n==='content-type'?mime:String(declared)},
 body:{getReader:()=>{let read=false;return {read:async()=>read?{done:true}:(read=true,{done:false,value:new Uint8Array(content)}),releaseLock:()=>{}};}}})};
vm.createContext(context);
'''
        runner = setup + '\nconst extract = vm.runInContext(' + json.dumps('(' + helper + ')') + ', context);\n'
        runner += '(async()=>{' + scenario + "\n})().catch(e=>{console.error(e);process.exitCode=1;});"
        result = subprocess.run(['node'], input=runner, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_js_vue_component_pages_not_thumbnail_count(self):
        self.run_browser_fixture(r'''
const result = await extract({action:'probe'});
assert.equal(result.pages,7);
assert.equal(result.course,'示例课程');
assert.equal(result.source_origin,'https://data.traingo.cn');
assert.equal(result.chapters.length,1);
assert.equal(JSON.stringify(result).includes('signature'),false);
assert.equal(JSON.stringify(result).includes('fixture-secret'),false);
assert.equal(JSON.stringify(result).includes('synthetic.pdf'),false);
photo.props.pages=0;
assert.equal((await extract({action:'probe'})).error,'invalid_document');
''')

    def test_js_fetch_chunk_clear_and_limits(self):
        self.run_browser_fixture(r'''
const expected = await extract({action:'probe'});
const nonce = 'a'.repeat(32), request={action:'start',nonce,expected,max_bytes:1024,fetch_timeout:10};
const start = await extract(request);
assert.equal(start.size,content.length);
assert.equal(JSON.stringify(start).includes('fixture-secret'),false);
const chunk = await extract({action:'chunk',nonce,offset:0,length:4});
assert.equal(Buffer.from(chunk.data,'base64').toString(),'%PDF');
assert.equal((await extract({action:'clear',nonce})).cleared,true);
assert.equal((await extract({action:'chunk',nonce,offset:0,length:4})).error,'cache_expired');
mime='text/html';
assert.equal((await extract(request)).error,'not_pdf_mime');
mime='application/pdf'; declared=2048;
assert.equal((await extract(request)).error,'size_limit');
declared=0; content=Buffer.alloc(1025);
assert.equal((await extract(request)).error,'size_limit');
content=Buffer.from('<html>blocked</html>');
assert.equal((await extract(request)).error,'not_pdf_magic');
context.fetch=async()=>{throw new Error('https://data.traingo.cn/private?fixture-secret');};
const error = await extract(request);
assert.equal(error.error,'browser_operation_failed');
assert.equal(JSON.stringify(error).includes('fixture-secret'),false);
''')

    def test_js_fail_closed_exam_route_and_ambiguous_document(self):
        self.run_browser_fixture(r'''
context.location.pathname='/exam/detail';
assert.equal((await extract({action:'probe'})).error,'not_course_view');
context.location.pathname='/course/detail'; row.innerText='在线考试'; row.querySelectorAll=()=>[el('在线考试')];
assert.equal((await extract({action:'probe'})).error,'ambiguous_or_exam_chapter');
row.innerText='第一章'; row.querySelectorAll=()=>[el('第一章')];
root.subTree.children=[];root.subTree.dynamicChildren=[];
assert.equal((await extract({action:'probe'})).error,'ambiguous_document');
root.subTree.children=[vnode,{component:{...photo}}];
assert.equal((await extract({action:'probe'})).error,'ambiguous_document');
''')

    def test_js_document_identity_race_and_cache_expiry(self):
        self.run_browser_fixture(r'''
const expected = await extract({action:'probe'}), nonce='b'.repeat(32);
const request={action:'start',nonce,expected,max_bytes:1024,fetch_timeout:10};
photo.props.pages=8;
assert.equal((await extract(request)).error,'document_changed');
photo.props.pages=7;
assert.equal((await extract(request)).size,content.length);
for(const timer of timers)timer();
assert.equal((await extract({action:'chunk',nonce,offset:0,length:4})).error,'cache_expired');
''')

    def test_help_is_browser_free(self):
        p = subprocess.run(['python3', str(ROOT / 'scripts/extract_course.py'), '--help'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertIn('--download', p.stdout)
        self.assertIn('--probe', p.stdout)


def fixture():
    return {'course': '示例课程', 'chapter': '第一章', 'chapter_index': 0, 'pages': 7,
            'source_origin': 'https://data.traingo.cn',
            'chapters': [{'index': 0, 'title': '第一章', 'active': True, 'exam': False, 'progress': 0}]}


if __name__ == '__main__':
    unittest.main()
