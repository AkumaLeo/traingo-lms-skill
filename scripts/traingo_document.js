/* Browser-only function. Never return source URLs, headers, Vue state or errors.
 * Only the currently displayed explicit Photo document may be fetched.
 * No navigation, chapter clicks, login handling, playback or canvas extraction.
 */
async function traingoDocument(request) {
  const fail = code => { throw new Error(code); };
  const key = Symbol.for('traingo.document.bytes.v1');
  const cache = window[key] || (window[key] = new Map());
  const stable = metadata => JSON.stringify({
    course: metadata.course, chapter: metadata.chapter, chapter_index: metadata.chapter_index,
    pages: metadata.pages, source_origin: metadata.source_origin,
    chapters: metadata.chapters.map(({index,title,active,exam}) => ({index,title,active,exam}))
  });
  const now = Date.now();
  for (const [nonce, entry] of cache) {
    if (now >= entry.expires) cache.delete(nonce);
  }
  const visible = e => !!(e && e.getClientRects && e.getClientRects().length &&
    getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none');
  const text = e => e ? String(e.innerText || e.textContent || '').trim() : '';
  const exam = value => /考试|测验|答题|试卷|问卷|exam|quiz|assessment|survey/i.test(value);
  const title = value => {
    if (!value || value.length > 500 || /https?:\/\/|[\x00-\x1f]/i.test(value)) fail('unsafe_title');
    return value;
  };
  const snapshot = () => {
    if (location.protocol !== 'https:' || !/(^|\.)traingo\.cn$/.test(location.hostname) ||
        location.pathname !== '/course/detail') fail('not_course_view');
    if (document.querySelector('input[type="password"]') ||
        Array.from(document.querySelectorAll('[role="dialog"],.el-dialog,.el-message-box')).some(visible)) fail('auth_or_dialog');
    const headings = Array.from(document.querySelectorAll(request.course_selector || '.course-title,.course-name,h1'))
      .filter(visible).map(text).filter(Boolean);
    const unique = [...new Set(headings)];
    if (unique.length !== 1) fail('ambiguous_course_title');
    const course = title(unique[0]);
    if (exam(course)) fail('exam_not_allowed');
    const rows = Array.from(document.querySelectorAll('ul.chapter li')).filter(visible);
    if (!rows.length) fail('missing_catalog');
    const chapters = rows.map((row, index) => {
      const names = Array.from(row.querySelectorAll(request.chapter_selector || '.chapter-title,.chapter-name,.name,.title')).map(text).filter(Boolean);
      const distinct = [...new Set(names)];
      if (distinct.length > 1) fail('ambiguous_chapter_title');
      const name = title(distinct[0] || String(row.innerText || row.textContent || '').split('\n')[0].trim());
      const progress = text(row).match(/进度\s*[：:]\s*(\d+(?:\.\d+)?)\s*%/);
      const p = progress ? Number(progress[1]) : null;
      if (p !== null && (p < 0 || p > 100)) fail('invalid_progress');
      return {index, title: name, active: row.classList.contains('on'), exam: exam(text(row)), progress: p};
    });
    const active = chapters.filter(c => c.active);
    if (active.length !== 1 || active[0].exam) fail('ambiguous_or_exam_chapter');
    const root = document.querySelector('#app')?.__vue_app__?._container?._vnode?.component;
    const seen = new Set(), stack = [root], photos = [];
    let visited = 0;
    while (stack.length) {
      const node = stack.pop();
      if (!node || typeof node !== 'object' || seen.has(node)) continue;
      seen.add(node);
      if (++visited > 50000) fail('vue_tree_limit');
      if (node.vnode && node.subTree && node.type && (node.type.name === 'Photo' || node.type.__name === 'Photo') && node.props &&
          visible(node.vnode?.el || node.subTree?.el || node.el)) photos.push(node);
      if (node.subTree) stack.push(node.subTree);
      if (node.component) stack.push(node.component);
      if (Array.isArray(node.children)) stack.push(...node.children);
      if (Array.isArray(node.dynamicChildren)) stack.push(...node.dynamicChildren);
    }
    if (photos.length !== 1) fail('ambiguous_document');
    const props = photos[0].props;
    const pages = Number(props.pages);
    if (!Number.isSafeInteger(pages) || pages < 1 || pages > 100000 || typeof props.src !== 'string' || !props.src) fail('invalid_document');
    const source = new URL(props.src, location.href);
    if (source.protocol !== 'https:' || !/(^|\.)traingo\.cn$/.test(source.hostname) || source.username || source.password) fail('unsupported_document_source');
    return {source: source.href, metadata: {course, chapter: active[0].title,
      chapter_index: active[0].index, pages, source_origin: source.origin, chapters}};
  };
  try {
    if (!/^[a-f0-9]{32}$/.test(request.nonce || '') && request.action !== 'probe') fail('invalid_nonce');
    if (request.action === 'clear') { cache.delete(request.nonce); return {cleared: true}; }
    if (request.action === 'probe') return snapshot().metadata;
    if (request.action === 'start') {
      const before = snapshot();
      if (stable(before.metadata) !== stable(request.expected)) fail('document_changed');
      if (!Number.isSafeInteger(request.max_bytes) || request.max_bytes < 1 || request.max_bytes > 104857600 ||
          !Number.isFinite(request.fetch_timeout) || request.fetch_timeout < 1 || request.fetch_timeout > 120) fail('invalid_limits');
      const cacheSeconds = request.cache_seconds ?? 180;
      if (!Number.isFinite(cacheSeconds) || cacheSeconds < 1 || cacheSeconds > 1805) fail('invalid_limits');
      // One entry per request; no persistent browser storage or URL serialization.
      if (cache.size >= 2) fail('cache_busy');
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), request.fetch_timeout * 1000);
      try {
        const response = await fetch(before.source, {credentials: 'include', signal: controller.signal});
        if (!response.ok || response.redirected) fail('download_denied');
        const mime = (response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
        if (!['application/pdf', 'application/octet-stream', 'binary/octet-stream'].includes(mime)) fail('not_pdf_mime');
        const length = Number(response.headers.get('content-length') || 0);
        if (length > request.max_bytes) fail('size_limit');
        if (!response.body) fail('stream_unavailable');
        const reader = response.body.getReader(), chunks = [];
        let size = 0;
        try {
          while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            size += value.byteLength;
            if (size > request.max_bytes) { controller.abort(); fail('size_limit'); }
            chunks.push(value);
          }
        } finally { reader.releaseLock(); }
        const bytes = new Uint8Array(size);
        let offset = 0;
        for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
        if (String.fromCharCode(...bytes.subarray(0, 5)) !== '%PDF-') fail('not_pdf_magic');
        const after = snapshot();
        if (after.source !== before.source || stable(after.metadata) !== stable(before.metadata)) fail('document_changed');
        cache.set(request.nonce, {bytes, expires: Date.now()+cacheSeconds*1000, source: before.source, metadata: before.metadata});
        setTimeout(() => cache.delete(request.nonce), cacheSeconds*1000);
        return {metadata: before.metadata, size};
      } finally { clearTimeout(timer); }
    }
    if (request.action === 'chunk') {
      const entry = cache.get(request.nonce);
      if (!entry) fail('cache_expired');
      const current = snapshot();
      if (current.source !== entry.source || stable(current.metadata) !== stable(entry.metadata)) fail('document_changed');
      if (!Number.isSafeInteger(request.offset) || request.offset < 0 || request.offset >= entry.bytes.length ||
          !Number.isSafeInteger(request.length) || request.length < 1 || request.length > 262144) fail('invalid_chunk');
      const bytes = entry.bytes.subarray(request.offset, request.offset + request.length);
      let binary = '';
      for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      return {offset: request.offset, data: btoa(binary)};
    }
    fail('unknown_action');
  } catch (error) {
    // Never propagate fetch/DOM exception strings: they can contain signed URLs.
    const allowed = new Set(['not_course_view','auth_or_dialog','unsafe_title','ambiguous_course_title','exam_not_allowed',
      'missing_catalog','ambiguous_chapter_title','invalid_progress','ambiguous_or_exam_chapter','vue_tree_limit',
      'ambiguous_document','invalid_document','unsupported_document_source','invalid_nonce','document_changed',
      'invalid_limits','cache_busy','download_denied','not_pdf_mime','size_limit','stream_unavailable','not_pdf_magic',
      'cache_expired','invalid_chunk','unknown_action']);
    return {error: allowed.has(error.message) ? error.message : 'browser_operation_failed'};
  }
}
