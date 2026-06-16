/*
 * Phase 0 — measure.js
 * indexer(휴리스틱) + oracle(jQuery 정답지) 를 한 번에 돌려 버킷 분류 리포트를 만든다.
 *
 *  - same-origin iframe 자동 순회 (운영자가 콘솔에서 프레임 전환 안 하게)
 *  - shadow DOM 유무 체크
 *  - performance.now() 로 인덱스 빌드 시간 측정
 *  - 결과를 클립보드 복사 + 콘솔 출력
 *
 * 버킷:
 *  caught-native    : 휴리스틱이 잡음 + 네이티브 인터랙티브 태그 (항상 정상)
 *  caught-aria      : 휴리스틱이 잡음 + ARIA role/state + jQuery 핸들러 확인됨
 *  caught-keyword   : 휴리스틱이 잡음 + id/class 키워드 + jQuery 핸들러 확인됨
 *  caught-pointer   : 휴리스틱이 잡음 + cursor:pointer + jQuery 핸들러 확인됨
 *  caught-other     : 휴리스틱이 잡음 + tabindex/onclick + jQuery 핸들러 확인됨
 *  FPcandidate-*    : 휴리스틱이 잡았지만 jQuery 핸들러 없음 & 네이티브도 아님 (오탐 후보 = 잡음)
 *  MISSED 🔴        : 휴리스틱이 못 잡았는데 jQuery 핸들러가 있음 (놓친 진짜 버튼 — 핵심 위험)
 */
(function () {
  const P0 = (window.__P0 = window.__P0 || {});

  function collectFrames(win, acc, path) {
    acc.push({ win: win, doc: win.document, path: path });
    const iframes = win.document.querySelectorAll('iframe, frame');
    for (let i = 0; i < win.frames.length; i++) {
      let childWin = null, accessible = true;
      try { childWin = win.frames[i]; void childWin.document; } catch (e) { accessible = false; }
      const frameEl = iframes[i];
      const label = frameEl ? (frameEl.name || frameEl.id || 'frame' + i) : 'frame' + i;
      if (accessible && childWin) collectFrames(childWin, acc, path + '>' + label);
      else acc.push({ crossOrigin: true, path: path + '>' + label });
    }
    return acc;
  }

  function shadowCount(doc) {
    let n = 0;
    doc.querySelectorAll('*').forEach((el) => { if (el.shadowRoot) n++; });
    return n;
  }

  function bucketOf(sig, oracleRec) {
    const hasHandler = !!oracleRec;
    if (sig.length === 0) return hasHandler ? 'MISSED' : null;
    const isNative = sig.some((s) => s.indexOf('native:') === 0);
    if (isNative) return 'caught-native';
    const kind =
      sig.some((s) => s.indexOf('role:') === 0 || s.indexOf('aria-') === 0) ? 'aria'
        : sig.some((s) => s.indexOf('keyword:') === 0) ? 'keyword'
          : sig.indexOf('cursor-pointer') >= 0 ? 'pointer'
            : 'other';
    return (hasHandler ? 'caught-' : 'FPcandidate-') + kind;
  }

  function cell(s) {
    return String(s == null ? '' : s).replace(/\|/g, '/').replace(/\n/g, ' ').slice(0, 70);
  }

  function buildReport(d) {
    const L = [];
    const order = [
      'caught-native', 'caught-aria', 'caught-keyword', 'caught-pointer', 'caught-other',
      'FPcandidate-aria', 'FPcandidate-keyword', 'FPcandidate-pointer', 'FPcandidate-other',
      'MISSED',
    ];
    L.push('===== PHASE 0 GROUNDING REPORT =====');
    L.push('url: ' + location.href);
    L.push('time: ' + new Date().toISOString());
    L.push('ua: ' + navigator.userAgent);
    L.push('');
    L.push('-- frames --');
    L.push('accessible frames: ' + d.frames.filter((f) => !f.crossOrigin).length);
    L.push('cross-origin frames (unreadable, silent-zero): ' + d.crossOriginFrames);
    L.push('shadow DOM hosts found: ' + d.totalShadow + (d.totalShadow ? '  ⚠️ querySelectorAll 가 못 뚫음 — 별도 처리 필요' : '  (ok)'));
    L.push('');
    L.push('-- jQuery oracle (answer key) --');
    if (d.oracleSummary) {
      L.push('jQuery available: yes   version: ' + d.oracleSummary.version);
      L.push('binding style: ' + d.oracleSummary.bindingStyle +
        '  (direct=' + d.oracleSummary.directCount + ', delegated=' + d.oracleSummary.delegatedCount +
        ', delegatedRules=' + d.oracleSummary.delegatedRuleCount + ')');
      if (d.oracleSummary.bindingStyle === 'delegated') {
        L.push('  ⚠️ 위임이 우세 — 요소별 핸들러 탐지가 불안정. §3 재설계 신호일 수 있음.');
      }
    } else {
      L.push('jQuery available: NO  ⚠️ 이 화면엔 jQuery 가 없음 → oracle 채점 불가 (휴리스틱 결과만 봄).');
    }
    L.push('');
    L.push('-- timing --');
    L.push('index build: ' + d.buildMs + ' ms   candidates: ' + d.rows.length);
    L.push('');
    L.push('-- bucket counts --');
    for (const k of order) if (d.buckets[k]) L.push('  ' + k + ': ' + d.buckets[k]);
    L.push('');

    const missed = d.rows.filter((r) => r.bucket === 'MISSED');
    L.push('-- 🔴 MISSED (휴리스틱이 놓친, 핸들러 있는 요소) : ' + missed.length + ' --');
    for (const r of missed) L.push('  [' + r.frame + '] <' + r.tag + '> id=' + cell(r.id) + ' | ' + cell(r.text) + ' | jq=' + r.oracle);
    L.push('');

    L.push('-- full candidate table --');
    L.push('| frame | tag | id | text | caught? | signals | jq | bucket |');
    L.push('|---|---|---|---|---|---|---|---|');
    const cap = 500;
    d.rows.slice(0, cap).forEach((r) => {
      L.push('| ' + cell(r.frame) + ' | ' + r.tag + ' | ' + cell(r.id) + ' | ' + cell(r.text) +
        ' | ' + (r.caught ? 'Y' : 'N') + ' | ' + cell(r.signals.join(',')) + ' | ' + (r.oracle || '-') + ' | ' + r.bucket + ' |');
    });
    if (d.rows.length > cap) L.push('| ... (' + (d.rows.length - cap) + ' more rows truncated) | | | | | | | |');
    L.push('');
    L.push('===== END — 이 전체 텍스트를 Claude 에게 붙여넣으세요 =====');
    return L.join('\n');
  }

  function copy(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (res, rej) {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        res();
      } catch (e) { rej(e); }
    });
  }

  function run(opts) {
    opts = opts || {};
    const t0 = performance.now();
    const frames = collectFrames(window, [], 'top');
    const rows = [];
    const buckets = {};
    let crossOriginFrames = 0;
    let totalShadow = 0;
    let oracleSummary = null;

    for (const f of frames) {
      if (f.crossOrigin) { crossOriginFrames++; continue; }
      totalShadow += shadowCount(f.doc);
      const idx = P0.indexInteractive(f.doc, f.win); // C
      const oracle = P0.jqueryOracle(f.doc, f.win); // O
      if (oracle.available) {
        if (!oracleSummary) oracleSummary = Object.assign({}, oracle);
        else {
          oracleSummary.directCount += oracle.directCount;
          oracleSummary.delegatedCount += oracle.delegatedCount;
          oracleSummary.delegatedRuleCount += oracle.delegatedRuleCount;
        }
      }

      const caughtMap = new Map(idx.map((o) => [o.el, o]));
      const candidateEls = new Set(idx.map((o) => o.el));
      if (oracle.available) for (const el of oracle.map.keys()) candidateEls.add(el);

      for (const el of candidateEls) {
        const o = caughtMap.get(el);
        const sig = o ? o.signals : [];
        const oracleRec = oracle.available ? oracle.map.get(el) : undefined;
        const b = bucketOf(sig, oracleRec);
        if (!b) continue;
        buckets[b] = (buckets[b] || 0) + 1;
        rows.push({
          frame: f.path,
          tag: (el.tagName || '?').toLowerCase(),
          id: el.id || '',
          text: P0._accessibleName(el),
          caught: !!o,
          signals: sig,
          oracle: oracleRec ? ((oracleRec.direct ? 'direct' : '') + (oracleRec.delegated ? (oracleRec.direct ? '+deleg' : 'deleg') : '')) : '',
          bucket: b,
        });
      }
    }
    const buildMs = Math.round(performance.now() - t0);

    const report = buildReport({ rows, buckets, frames, crossOriginFrames, totalShadow, oracleSummary, buildMs });
    copy(report).then(
      function () { console.log('%c[Phase0] ✅ 리포트가 클립보드에 복사됨 — Claude 에게 붙여넣으세요.', 'color:green;font-weight:bold;font-size:13px'); },
      function () { console.log('%c[Phase0] ⚠️ 클립보드 복사 실패 — 아래 콘솔 출력을 직접 복사하세요.', 'color:orange;font-weight:bold'); }
    );
    console.log(report);
    return report;
  }

  P0.run = run;
})();
