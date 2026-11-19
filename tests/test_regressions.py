"""Publication regressions; all browser objects and course data are synthetic."""
import copy
import tempfile
import unittest
from pathlib import Path
import test_watch as tw
import test_extract as te


class PublicationRegressions(unittest.TestCase):
    def test_sidebar_exam_is_skipped_and_online_completion_is_separate(self):
        s = tw.snap()
        s['chapters'][1]['title'] = '在线考试'
        with tempfile.TemporaryDirectory() as directory:
            adapter = tw.Fake([s])
            monitor = tw.w.Monitor(tw.config(), Path(directory), adapter, True)
            self.assertEqual(monitor.tick(), 'complete')
            self.assertEqual(adapter.actions, [])

    def test_chapter_action_pins_observed_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter=tw.Fake([tw.snap()])
            self.assertEqual(tw.w.Monitor(tw.config(),Path(directory),adapter,True).tick(),'acted')
            self.assertEqual(adapter.actions[0]['expected_chapters'],[
                {'title':'Synthetic chapter A','current':True,'exam':False},
                {'title':'Synthetic chapter B','current':False,'exam':False}])

    def test_extractor_excludes_surveys(self):
        for title in ['问卷','survey']:
            metadata=te.fixture()
            metadata['chapter']=title
            metadata['chapters'][0]['title']=title
            with self.subTest(title=title), self.assertRaises(te.m.ExtractError):
                te.m.validate_metadata(metadata)
        te.ExtractionTests().run_browser_fixture(r'''
row.innerText='问卷'; row.querySelectorAll=()=>[el('问卷')];
assert.equal((await extract({action:'probe'})).error,'ambiguous_or_exam_chapter');
''')

    def test_current_exam_never_operated(self):
        s = tw.snap()
        s['chapters'][0]['title'] = '测验'
        with tempfile.TemporaryDirectory() as directory:
            adapter = tw.Fake([s])
            self.assertEqual(tw.w.Monitor(tw.config(), Path(directory), adapter, True).tick(), 'safety_stop')
            self.assertEqual(adapter.actions, [])

    def test_exam_target_configuration_refused(self):
        for changes in [{'title': '在线考试'}, {'url': 'https://example.invalid/exam/detail'}]:
            value = tw.config()
            value['courses'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(tw.w.SafeError):
                tw.w.validate_config(value)

    def test_chunk_rejects_same_metadata_different_source(self):
        te.ExtractionTests().run_browser_fixture(r'''
const expected=await extract({action:'probe'}), nonce='d'.repeat(32);
assert.equal((await extract({action:'start',nonce,expected,max_bytes:1024,fetch_timeout:10})).size,content.length);
photo.props.src='//data.traingo.cn/different.pdf?signature=another-fixture';
assert.equal((await extract({action:'chunk',nonce,offset:0,length:4})).error,'document_changed');
''')

    def test_large_document_transfer_has_bounded_sufficient_budget(self):
        import base64
        from unittest.mock import patch
        clock=[0.0]
        size=70*1024*1024
        class Browser:
            def call(self, action, **kwargs):
                if action=='start': return {'metadata':te.fixture(),'size':size}
                if action=='chunk':
                    clock[0]+=2
                    length=kwargs['length']
                    return {'offset':kwargs['offset'],'data':base64.b64encode(b'0'*length).decode()}
                return {'cleared':True}
        with tempfile.TemporaryDirectory() as directory, patch.object(te.m.time,'monotonic',side_effect=lambda:clock[0]), patch.object(te.m,'validate_pdf',return_value=7):
            result=te.m.download(Browser(),te.fixture(),Path(directory),80*1024*1024,te.m.CHUNK_BYTES,900)
            self.assertEqual(result['bytes'],size)
            self.assertGreater(clock[0],180)
            self.assertLess(clock[0],900)

    def test_download_ignores_changing_progress_but_pins_document(self):
        te.ExtractionTests().run_browser_fixture(r'''
const expected = await extract({action:'probe'}), nonce='c'.repeat(32);
const fetchOriginal=context.fetch;
context.fetch=async (...args)=>{
  row.innerText='第一章\n进度：1%';
  return fetchOriginal(...args);
};
const started=await extract({action:'start',nonce,expected,max_bytes:1024,fetch_timeout:10});
assert.equal(started.size,content.length);
row.innerText='第一章\n进度：2%';
const chunk=await extract({action:'chunk',nonce,offset:0,length:4});
assert.equal(Buffer.from(chunk.data,'base64').toString(),'%PDF');
assert.equal((await extract({action:'clear',nonce})).cleared,true);
''')


if __name__ == '__main__':
    unittest.main()
