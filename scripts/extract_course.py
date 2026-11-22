#!/usr/bin/env python3
"""Authorized current-document PDF extraction; Python 3.9+, OpenCLI 2.0.2.

Default/--probe is read-only metadata inspection (no PDF fetch). --download is
explicit consent to fetch ONLY the currently open course document. Optional
PyMuPDF is imported only for download validation. Never export browser cookies,
URLs, auth stores or storage. No login, captcha, exams or access-control bypass.

Batch is an AGENT WORKFLOW, not unattended chapter navigation: --probe enumerates
visible catalog indices/exact titles. Validate configured targets, manually open
ONE authorized document, run with --expect-course/--chapter-index/--chapter-title,
and repeat. This CLI never changes chapters, so has no UI restoration operation.
The agent/operator must restore the earliest unfinished authorized chapter if
THEY change the UI; unknown progress/authorization requires human review.
"""
import argparse
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

# -I source execution omits the script directory; trust only this bundled sibling.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_argv import build_argv
import tempfile
import time
import uuid

MAX_BYTES = 100 * 1024 * 1024
CHUNK_BYTES = 192 * 1024


class ExtractError(Exception):
    """Fixed privacy-safe codes, never raw browser or operating-system errors."""


def safe_name(title):
    if not isinstance(title, str) or not title or title in ('.', '..'):
        raise ExtractError('invalid_title')
    # Preserve all other Unicode, punctuation, spaces and title content exactly.
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title)
    if name in ('.', '..'):
        raise ExtractError('invalid_title')
    return name


def _title(value):
    return (isinstance(value, str) and 0 < len(value) <= 500 and
            not re.search(r'https?://|[\x00-\x1f]', value, re.I))


def validate_metadata(meta, expected_course=None, chapter_index=None, chapter_title=None):
    if not isinstance(meta, dict) or set(meta) != {'course', 'chapter', 'chapter_index', 'pages', 'source_origin', 'chapters'}:
        raise ExtractError('invalid_metadata')
    if not all(_title(meta[k]) for k in ('course', 'chapter')):
        raise ExtractError('invalid_metadata')
    if re.search(r'考试|测验|答题|试卷|问卷|exam|quiz|assessment|survey', meta['course'] + meta['chapter'], re.I):
        raise ExtractError('exam_not_allowed')
    origin = meta['source_origin']
    if not isinstance(origin, str) or not re.fullmatch(r'https://(?:[a-zA-Z0-9-]+\.)*traingo\.cn(?::\d{1,5})?', origin):
        raise ExtractError('invalid_source_origin')
    if type(meta['pages']) is not int or not 1 <= meta['pages'] <= 100000:
        raise ExtractError('invalid_viewer_pages')
    chapters = meta['chapters']
    if not isinstance(chapters, list) or not chapters or len(chapters) > 10000:
        raise ExtractError('invalid_catalog')
    for i, chapter in enumerate(chapters):
        if (not isinstance(chapter, dict) or set(chapter) != {'index', 'title', 'active', 'exam', 'progress'} or
                type(chapter['index']) is not int or chapter['index'] != i or not _title(chapter['title']) or
                type(chapter['active']) is not bool or type(chapter['exam']) is not bool):
            raise ExtractError('invalid_catalog')
        p = chapter['progress']
        if p is not None and (type(p) not in (int, float) or not 0 <= p <= 100):
            raise ExtractError('invalid_catalog')
    active = [c for c in chapters if c['active']]
    if (len(active) != 1 or active[0]['exam'] or type(meta['chapter_index']) is not int or
            active[0]['index'] != meta['chapter_index'] or active[0]['title'] != meta['chapter']):
        raise ExtractError('ambiguous_current_chapter')
    if expected_course is not None and meta['course'] != expected_course:
        raise ExtractError('course_mismatch')
    if chapter_index is not None and meta['chapter_index'] != chapter_index:
        raise ExtractError('chapter_index_mismatch')
    if chapter_title is not None and meta['chapter'] != chapter_title:
        raise ExtractError('chapter_title_mismatch')
    return meta


class Browser:
    def __init__(self, executable='opencli', session='traingo-extract', profile=None, timeout=45,
                 course_selector=None, chapter_selector=None):
        self.executable, self.session, self.profile, self.timeout = executable, session, profile, timeout
        self.selectors = {'course_selector': course_selector, 'chapter_selector': chapter_selector}

    def evaluate(self, expression):
        args = [self.executable, 'browser', 'eval', '--session', self.session]
        if self.profile:
            args.extend(['--profile', self.profile])
        args.append(expression)
        try:
            result = subprocess.run(build_argv(args[0], args[1:]), capture_output=True,
                                    text=True, encoding='utf-8', timeout=self.timeout, shell=False)
            if result.returncode:
                raise ExtractError('browser_command_failed')
            if len(result.stdout) > 2 * 1024 * 1024:
                raise ExtractError('browser_response_limit')
            envelope = json.loads(result.stdout)
            if not isinstance(envelope, dict) or envelope.get('ok') is not True or 'data' not in envelope:
                raise ExtractError('browser_response_invalid')
            return envelope['data']
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            raise ExtractError('browser_command_failed') from None

    def call(self, action, **kwargs):
        try:
            source = Path(__file__).with_name('traingo_document.js').read_text(encoding='utf-8')
        except OSError:
            raise ExtractError('browser_helper_unavailable') from None
        request = dict(self.selectors, action=action, **kwargs)
        result = self.evaluate('(' + source + ')(' + json.dumps(request, ensure_ascii=False) + ')')
        if not isinstance(result, dict) or 'error' in result:
            # Do not trust or echo even a purported browser error code.
            raise ExtractError('browser_operation_failed_use_official_download')
        return result


def validate_pdf(data, pages):
    if not data.startswith(b'%PDF-'):
        raise ExtractError('not_pdf_magic')
    try:
        import fitz
    except ImportError:
        raise ExtractError('pymupdf_required_for_validation') from None
    try:
        with fitz.open(stream=data, filetype='pdf') as doc:
            if doc.needs_pass:
                raise ExtractError('encrypted_pdf_not_supported')
            if doc.page_count != pages:
                raise ExtractError('viewer_page_count_mismatch')
            # Parsing all pages catches damaged page trees; never render or OCR.
            for i in range(doc.page_count):
                doc.load_page(i)
            return doc.page_count
    except ExtractError:
        raise
    except Exception:
        raise ExtractError('invalid_pdf') from None


def atomic_save(path, data, overwrite=False):
    """Same-directory atomic publish; link prevents race-based overwrites."""
    path = Path(path)
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.extract-', suffix='.tmp', dir=str(path.parent))
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != data:
                    raise ExtractError('output_exists_different') from None
        return path
    except OSError:
        raise ExtractError('output_write_failed') from None
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def download(browser, metadata, output_dir, max_bytes, chunk_bytes, timeout, overwrite=False):
    validate_metadata(metadata)
    if (type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES or
            type(chunk_bytes) is not int or not 1 <= chunk_bytes <= 262144 or not 1 <= timeout <= 1800):
        raise ExtractError('invalid_limits')
    nonce = uuid.uuid4().hex
    started = time.monotonic()
    cleaned = False
    original_timeout = browser.timeout if isinstance(browser, Browser) else None

    def transfer(action, **kwargs):
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise ExtractError('download_timeout')
        if original_timeout is not None:
            browser.timeout = min(original_timeout, remaining)
        return browser.call(action, **kwargs)

    try:
        result = transfer('start', nonce=nonce, expected=metadata, max_bytes=max_bytes, fetch_timeout=min(timeout,120), cache_seconds=timeout+5)
        if result.get('metadata') != metadata:
            raise ExtractError('document_changed')
        size = result.get('size')
        if type(size) is not int or not 5 <= size <= max_bytes:
            raise ExtractError('invalid_download_size')
        data = bytearray()
        while len(data) < size:
            if time.monotonic() - started > timeout:
                raise ExtractError('download_timeout')
            length = min(chunk_bytes, size - len(data))
            chunk = transfer('chunk', nonce=nonce, offset=len(data), length=length)
            if chunk.get('offset') != len(data) or not isinstance(chunk.get('data'), str):
                raise ExtractError('invalid_chunk')
            try:
                decoded = base64.b64decode(chunk['data'], validate=True)
            except (ValueError, binascii.Error):
                raise ExtractError('invalid_chunk') from None
            if len(decoded) != length:
                raise ExtractError('invalid_chunk_length')
            data.extend(decoded)
        # Free in-page bytes before optional CPU validation / file publication.
        if time.monotonic() - started > timeout:
            raise ExtractError('download_timeout')
        if original_timeout is not None:
            browser.timeout = min(original_timeout, 5)
        if browser.call('clear', nonce=nonce).get('cleared') is not True:
            raise ExtractError('cache_cleanup_failed')
        cleaned = True
        payload = bytes(data)
        actual_pages = validate_pdf(payload, metadata['pages'])
        filename = safe_name(metadata['course']) + ' — ' + safe_name(metadata['chapter']) + '.pdf'
        manifest = {'schema_version': 1, 'course': metadata['course'], 'chapter': metadata['chapter'],
                    'chapter_index': metadata['chapter_index'], 'filename': filename,
                    'source_origin': metadata['source_origin'], 'viewer_pages': metadata['pages'],
                    'pdf_pages': actual_pages, 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
        output_dir = Path(output_dir)
        manifest_data = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        manifest_path = output_dir / (filename + '.manifest.json')
        # Preflight sidecar collisions to avoid a predictable partial pair.
        if not overwrite and manifest_path.exists() and (manifest_path.is_symlink() or manifest_path.read_bytes() != manifest_data):
            raise ExtractError('manifest_exists_different')
        atomic_save(output_dir / filename, payload, overwrite)
        atomic_save(manifest_path, manifest_data, overwrite)
        return manifest
    finally:
        if not cleaned:
            try:
                if original_timeout is not None:
                    browser.timeout = min(original_timeout, 5)
                browser.call('clear', nonce=nonce)
            except Exception:
                # Browser-side cache also expires automatically within the bounded transfer budget.
                pass
        if original_timeout is not None:
            browser.timeout = original_timeout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--probe', action='store_true', help='metadata/catalog only; default; no document fetch')
    mode.add_argument('--download', action='store_true', help='opt in to original current PDF download')
    parser.add_argument('--opencli', default=os.environ.get('OPENCLI_EXECUTABLE', 'opencli'))
    parser.add_argument('--session', default='traingo-extract', help='owned authenticated browser session')
    parser.add_argument('--profile', help='OpenCLI browser profile name; never reads profile files')
    parser.add_argument('--output-dir', type=Path, help='required with --download')
    parser.add_argument('--expect-course', help='exact title; required with --download')
    parser.add_argument('--chapter-index', type=int, help='zero-based visible catalog index; required with --download')
    parser.add_argument('--chapter-title', help='exact title; required with --download')
    parser.add_argument('--course-selector', help='visible course title CSS selector when default is ambiguous')
    parser.add_argument('--chapter-selector', help='chapter title CSS selector relative to ul.chapter li')
    parser.add_argument('--overwrite', action='store_true', help='explicitly replace different PDF/manifest files')
    parser.add_argument('--max-bytes', type=int, default=80 * 1024 * 1024, help='PDF limit; hard maximum 100 MiB')
    parser.add_argument('--chunk-bytes', type=int, default=CHUNK_BYTES, help='1..262144; default 192 KiB')
    parser.add_argument('--timeout', type=int, default=900, help='overall download budget 1..1800 seconds; fetch capped at 120')
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 1800 or not 1 <= args.max_bytes <= MAX_BYTES or not 1 <= args.chunk_bytes <= 262144:
        parser.error('invalid size/chunk/timeout limits')
    if args.download and (args.output_dir is None or not args.expect_course or args.chapter_index is None or not args.chapter_title):
        parser.error('--download requires --output-dir, --expect-course, --chapter-index and --chapter-title')
    if args.chapter_index is not None and args.chapter_index < 0:
        parser.error('--chapter-index must be nonnegative')
    try:
        browser = Browser(args.opencli, args.session, args.profile, args.timeout + 5,
                          args.course_selector, args.chapter_selector)
        metadata = validate_metadata(browser.call('probe'), args.expect_course, args.chapter_index, args.chapter_title)
        result = download(browser, metadata, args.output_dir, args.max_bytes, args.chunk_bytes, args.timeout,
                          args.overwrite) if args.download else metadata
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ExtractError as error:
        print('extract: ' + str(error), file=sys.stderr)
        return 1
    except Exception:
        print('extract: operation_failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
