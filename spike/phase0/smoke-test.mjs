/*
 * Phase 0 — smoke-test.mjs  (개발용, 배포 아님)
 * 합쳐진 측정 코드를 작은 가짜 DOM 에 돌려 파이프라인이 안 터지고 버킷이 맞는지 확인.
 * jsdom 같은 의존성 없이, 필요한 최소한만 흉내낸다. (레이아웃은 흉내 못 냄)
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const code = ['indexer.js', 'oracle.js', 'measure.js']
  .map((f) => readFileSync(join(here, f), 'utf8')).join('\n;\n');

// --- 가짜 요소 만들기 ---
function makeEl(spec) {
  const attrs = spec.attrs || {};
  const el = {
    tagName: spec.tag,
    id: attrs.id || '',
    className: attrs.class || '',
    value: spec.value,
    innerText: spec.text || '',
    textContent: spec.text || '',
    isContentEditable: !!spec.contentEditable,
    disabled: !!spec.disabled,
    hidden: !!spec.hidden,
    shadowRoot: null,
    _style: Object.assign({ display: 'block', visibility: 'visible', opacity: '1', cursor: 'auto' }, spec.style || {}),
    _events: spec.events || null,
    getAttribute(n) { return n in attrs ? attrs[n] : null; },
    hasAttribute(n) { return n in attrs; },
    getClientRects() { return spec.hidden ? [] : [{ width: 10, height: 10 }]; },
    matches(sel) {
      if (sel[0] === '.') return (' ' + (attrs.class || '') + ' ').indexOf(' ' + sel.slice(1) + ' ') >= 0;
      if (sel[0] === '#') return (attrs.id || '') === sel.slice(1);
      return el.tagName.toLowerCase() === sel.toLowerCase();
    },
    contains(other) { return other === el; },
  };
  return el;
}

const els = [
  makeEl({ tag: 'BUTTON', text: '검색', attrs: { id: 'mf_pfwork_btn_search' }, style: { cursor: 'pointer' }, events: { click: [{ selector: null }] } }),
  makeEl({ tag: 'INPUT', attrs: { id: 'mf_pfwork_ibx_csNo', type: 'text' } }),
  makeEl({ tag: 'INPUT', attrs: { id: 'hidden1', type: 'hidden' } }), // 신호 없음 → skip
  makeEl({ tag: 'DIV', text: '신청', attrs: { id: 'mf_pfwork_lbtn_apply', class: 'btnArea' }, style: { cursor: 'pointer' }, events: { click: [{ selector: null }] } }), // caught-keyword/pointer + handler
  makeEl({ tag: 'DIV', text: '숨은버튼', attrs: { id: 'plainDiv' }, events: { click: [{ selector: null }] } }), // 🔴 MISSED: 핸들러 있는데 신호 0
  makeEl({ tag: 'SPAN', text: '그냥라벨', attrs: { id: 'lbl1' }, style: { cursor: 'pointer' } }), // FPcandidate-pointer: 신호 있고 핸들러 없음
  makeEl({ tag: 'A', text: '위임링크', attrs: { id: 'd1', class: 'deleg', href: '#' }, events: null }), // native:a, 위임 매치
];

// 위임 규칙을 document 에 심는다
const docEvents = { click: [{ selector: '.deleg' }] };

const documentMock = {
  _events: docEvents,
  documentElement: { _events: null },
  body: { _events: null, contains: () => true },
  contains: () => true,
  querySelectorAll(sel) {
    if (sel === 'iframe, frame') return [];
    return els.slice();
  },
};

const windowMock = {
  document: documentMock,
  frames: { length: 0 },
  getComputedStyle(el) { return el._style; },
  jQuery: Object.assign(
    function () {},
    {
      fn: { jquery: '1.12.4' },
      _data(node, key) { return key === 'events' ? (node._events || undefined) : undefined; },
    }
  ),
};
windowMock.window = windowMock;

const navigatorMock = { userAgent: 'node-smoke', clipboard: { writeText: () => Promise.resolve() } };
const locationMock = { href: 'https://ecfs.scourt.go.kr/test' };
const performanceMock = { now: () => Number(process.hrtime.bigint() / 1000n) / 1000 };

const fn = new Function('window', 'document', 'navigator', 'location', 'performance', 'console', code + '\nreturn window.__P0.run();');
const report = fn(windowMock, documentMock, navigatorMock, locationMock, performanceMock, { log: () => {} });

// --- 검증 ---
function expect(cond, msg) { if (!cond) { console.error('FAIL: ' + msg); process.exitCode = 1; } else console.log('ok: ' + msg); }
expect(typeof report === 'string' && report.length > 0, 'report 생성됨');
expect(/MISSED.*: 1/.test(report) || /plainDiv/.test(report), '🔴 MISSED(plainDiv) 잡힘');
expect(/FPcandidate-pointer: 1/.test(report), 'FPcandidate-pointer(라벨) 잡힘');
expect(/caught-native:/.test(report), 'caught-native 존재');
expect(/binding style: per-element/.test(report), 'binding style 보고됨');
expect(/jQuery available: yes/.test(report), 'oracle 동작');
expect(!/hidden1/.test(report), 'hidden input 은 제외됨');
console.log('\n--- report preview (head) ---\n' + report.split('\n').slice(0, 22).join('\n'));
