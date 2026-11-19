/* DOM-only browser adapter. No network calls, storage, cookies, Vue internals,
 * credentials, exam interaction, hidden video playback, or global button clicks.
 * Evaluated as a function by OpenCLI; result never includes body/dialog text.
 */
function traingoPlayer(options) {
  'use strict';
  const normalize = value => String(value || '').replace(/\s+/gu, ' ').trim();
  const compact = value => normalize(value).replace(/\s/gu, '');
  const restricted = value => /考试|测验|答题|试卷|问卷|exam|quiz|assessment|survey/iu.test(value);
  const visible = el => !!el && el.getClientRects().length > 0 &&
    getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
  const all = selector => Array.from(document.querySelectorAll(selector)).filter(visible);
  const fail = () => ({ acted: false });
  const percentage = text => {
    const match = text.match(/进度\s*[:：]\s*(\d+(?:\.\d+)?)\s*%/u);
    return match ? Number(match[1]) : null;
  };
  let titleNodes;
  try { titleNodes = all(options.titleSelector); } catch (_) { return fail(); }
  const titles = titleNodes.map(el => normalize(el.textContent));
  const bodyText = normalize(document.body ? document.body.innerText : '');
  const identity = all('input[type="password"], input[autocomplete="one-time-code"], iframe[src*="captcha"], .captcha, .identity-verification').length > 0 ||
    /人脸识别|身份验证|实名认证|验证码|请先登录|扫码登录/u.test(bodyText);
  const exam = all('.exam-paper, .question-list, .quiz, [data-page="exam"]').length > 0 ||
    /\/exam(?:[/?#]|$)|\/quiz(?:[/?#]|$)/iu.test(location.href);
  const modalNodes = all('[role="dialog"], .el-message-box, .el-dialog, .layui-layer, .ant-modal, .modal');
  // Deduplicate nested modal wrappers, not independent simultaneous dialogs.
  const modals = modalNodes.filter(el => !modalNodes.some(other => other !== el && el.contains(other)));
  let dialog = 'none', continueButton = null;
  if (identity) dialog = 'identity';
  else if (/系统禁止同时学习多个课程/u.test(bodyText)) dialog = 'concurrent';
  else if (modals.length) {
    dialog = 'unknown';
    if (modals.length === 1) {
      const modal = modals[0];
      const text = compact(modal.innerText);
      const buttons = Array.from(modal.querySelectorAll('button, [role="button"], .el-button, .layui-layer-btn a')).filter(visible);
      const confirms = buttons.filter(el => compact(el.textContent) === '确定');
      if (/^(?:温馨提示|提示)?请确认您是否还在学习[?？]?确定$/u.test(text) && confirms.length === 1) {
        dialog = 'continue'; continueButton = confirms[0];
      }
    }
  } else if (/请确认您是否还在学习/u.test(bodyText)) {
    // Known words without a known, scoped dialog structure are NOT authorization.
    dialog = 'unknown';
  }
  const nodes = all('ul.chapter li');
  const chapters = nodes.map(el => {
    const title = el.querySelector('.chapter-title, .title, .name');
    return {
      title: normalize(title ? title.textContent : el.textContent.replace(/进度\s*[:：]\s*\d+(?:\.\d+)?\s*%/gu, '')),
      percent: percentage(normalize(el.textContent)),
      current: el.classList.contains('on'),
      exam: restricted(normalize(el.textContent) + ' ' + (el.getAttribute?.('data-type') || ''))
    };
  });
  const totals = Array.from(bodyText.matchAll(/总进度\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%/gu));
  const countdowns = Array.from(bodyText.matchAll(/再学\s*(\d{1,3}):(\d{2})/gu));
  const total = totals.length === 1 ? Number(totals[0][1]) : null;
  const countdown = countdowns.length === 1 && Number(countdowns[0][2]) < 60 ?
    Number(countdowns[0][1]) * 60 + Number(countdowns[0][2]) : null;
  const currentRestricted = chapters.some(c => c.current && c.exam);
  const courseRestricted = titles.some(restricted);
  const snapshot = {url: location.href, titles, kind: exam || currentRestricted || courseRestricted ? 'exam' : 'course', dialog, total, countdown, chapters};
  if (options.action.kind === 'inspect') return snapshot;
  const validPercent = p => typeof p === 'number' && Number.isFinite(p) && p >= 0 && p <= 100;
  const current = chapters.map((c, i) => c.current ? i : -1).filter(i => i >= 0);
  const identified = location.href === options.target.url && titles.length === 1 &&
    titles[0] === normalize(options.target.title) && !exam && !identity && !currentRestricted && !courseRestricted &&
    validPercent(total) && chapters.some(c => !c.exam) && current.length === 1 &&
    chapters.every(c => c.title && (c.exam || validPercent(c.percent)));
  if (!identified) return fail();
  const action = options.action;
  if (action.kind === 'continue') {
    if (dialog !== 'continue' || options.allowContinue !== true || !continueButton) return fail();
    continueButton.click();
    return {acted: true};
  }
  if (dialog !== 'none') return fail();
  if (action.kind === 'chapter') {
    const expected = action.expected_chapters;
    if (!Array.isArray(expected) || expected.length !== chapters.length ||
        chapters.some((c,i) => !expected[i] || c.title !== expected[i].title ||
          c.current !== expected[i].current || c.exam !== expected[i].exam)) return fail();
    const i = action.index;
    if (!Number.isInteger(i) || !nodes[i] || chapters[current[0]].percent !== 100 ||
        chapters[i].exam || chapters[i].percent >= 100 || i === current[0]) return fail();
    // Scope to the verified chapter row only; no course-card or exam buttons.
    nodes[i].click();
    return {acted: true};
  }
  if (action.kind === 'navigate') {
    if ((!chapters.some(c => c.exam) && total !== 100) || !chapters.filter(c => !c.exam).every(c => c.percent === 100)) return fail();
    const targets = options.allowedCourses.filter(c => c.url === action.url && c.url !== options.target.url);
    if (targets.length !== 1 || !targets[0].title || restricted(targets[0].title)) return fail();
    // Same explicitly bound tab, never `open` or duplicate learning tabs.
    location.assign(targets[0].url);
    return {acted: true};
  }
  return fail();
}
