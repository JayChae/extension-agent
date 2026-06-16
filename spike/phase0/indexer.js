/*
 * Phase 0 — scourt 그라운딩 스파이크
 * indexer.js — §3 멀티시그널 인터랙티브 요소 인덱서 (isolated-world 안전판)
 *
 * ★ 이 함수는 Phase 2 content script 의 핵심으로 그대로 재활용한다. ★
 *
 * isolated world 에서 *실제로 쓸 수 있는 신호만* 쓴다:
 *   - 페이지의 jQuery($) 사용 안 함
 *   - DevTools/CDP 전용 getEventListeners() 사용 안 함
 * 그래서 여기서 나오는 포착률은 Phase 2 가 그대로 재현할 수 있는 "정직한" 수치다.
 *
 * 중복 제거(컨테이너 dedup)는 일부러 안 한다 — 채점을 정확히 하려고 신호가 맞는
 * 요소를 전부 인덱싱한다. (dedup 은 Phase 2 의 다듬기 단계로 미룬다.)
 */
(function () {
  const P0 = (window.__P0 = window.__P0 || {});

  // eXBuilder6 / scourt 명명 규칙 + 일반 키워드 (id/class/name 에서 탐지)
  const KEYWORD_RE =
    /(_btn_|_lbtn_|_ibx_|_acp_|_sbx_|_rad_|_chk_|_grd_|_cell_|btn|button|link|submit|search|confirm)/i;

  const ROLE_INTERACTIVE = new Set([
    'button', 'link', 'checkbox', 'radio', 'tab', 'menuitem',
    'menuitemcheckbox', 'menuitemradio', 'option', 'combobox',
    'switch', 'treeitem', 'spinbutton', 'slider', 'textbox', 'searchbox',
  ]);

  const NATIVE_TAGS = new Set(['BUTTON', 'SELECT', 'TEXTAREA', 'SUMMARY']);
  const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'META', 'LINK', 'HEAD', 'NOSCRIPT', 'TITLE']);

  function classString(el) {
    const c = el.className;
    if (c == null) return '';
    if (typeof c === 'string') return c;
    if (c.baseVal != null) return c.baseVal; // SVGAnimatedString
    return '';
  }

  function isVisible(el, win) {
    if (el.hidden) return false;
    const cs = win.getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse') return false;
    if (parseFloat(cs.opacity) === 0) return false;
    if (el.getClientRects().length === 0) return false;
    return true;
  }

  function isDisabled(el) {
    if (el.disabled === true) return true;
    if (el.getAttribute('aria-disabled') === 'true') return true;
    return false;
  }

  function accessibleName(el) {
    const aria = el.getAttribute && el.getAttribute('aria-label');
    if (aria && aria.trim()) return aria.trim().slice(0, 80);
    const txt = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
    if (txt) return txt.slice(0, 80);
    const val = el.value;
    if (val && String(val).trim()) return String(val).trim().slice(0, 80);
    const ph = el.getAttribute && el.getAttribute('placeholder');
    if (ph) return ph.trim().slice(0, 80);
    const title = el.getAttribute && el.getAttribute('title');
    if (title) return title.trim().slice(0, 80);
    const name = el.getAttribute && el.getAttribute('name');
    if (name) return name.trim().slice(0, 80);
    return '';
  }

  // 요소에 맞은 신호들을 반환 (빈 배열 = 휴리스틱이 안 잡음)
  function signalsFor(el, win) {
    const sig = [];
    const tag = el.tagName;

    // 1) 네이티브 태그
    if (tag === 'A' && el.getAttribute('href') != null) sig.push('native:a');
    else if (tag === 'INPUT') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      if (t !== 'hidden') sig.push('native:input.' + t);
    } else if (NATIVE_TAGS.has(tag)) sig.push('native:' + tag.toLowerCase());
    else if (el.isContentEditable) sig.push('native:contenteditable');

    // 2) ARIA role
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (role && ROLE_INTERACTIVE.has(role)) sig.push('role:' + role);

    // 3) aria-expanded / pressed / haspopup
    if (el.hasAttribute('aria-expanded')) sig.push('aria-expanded');
    if (el.hasAttribute('aria-pressed')) sig.push('aria-pressed');
    if (el.hasAttribute('aria-haspopup')) sig.push('aria-haspopup');

    // 4) tabindex >= 0
    const ti = el.getAttribute('tabindex');
    if (ti != null && parseInt(ti, 10) >= 0) sig.push('tabindex');

    // 5) onclick 속성 (addEventListener 아님 — isolated 에서 보이는 건 속성뿐)
    if (el.hasAttribute('onclick')) sig.push('onclick-attr');

    // 6) cursor:pointer (호버 아닌 평상 상태)
    if (win.getComputedStyle(el).cursor === 'pointer') sig.push('cursor-pointer');

    // 7) id/class/name 키워드 (eXBuilder6 규칙 포함)
    const hay = (el.id || '') + ' ' + classString(el) + ' ' + (el.getAttribute('name') || '');
    const m = hay.match(KEYWORD_RE);
    if (m) sig.push('keyword:' + m[1].toLowerCase());

    return sig;
  }

  // 한 document 에 대해 인터랙티브 요소 인덱싱 → [{el, index, tag, id, name, text, signals, disabled}]
  function indexInteractive(doc, win) {
    const out = [];
    const all = doc.querySelectorAll('*');
    for (let i = 0; i < all.length; i++) {
      const el = all[i];
      if (SKIP_TAGS.has(el.tagName)) continue;
      if (!isVisible(el, win)) continue;
      const sig = signalsFor(el, win);
      if (sig.length === 0) continue;
      out.push({
        el: el,
        tag: el.tagName.toLowerCase(),
        id: el.id || '',
        name: (el.getAttribute('name') || ''),
        text: accessibleName(el),
        signals: sig,
        disabled: isDisabled(el),
      });
    }
    out.forEach((o, i) => (o.index = i));
    return out;
  }

  P0.indexInteractive = indexInteractive;
  P0._signalsFor = signalsFor;
  P0._isVisible = isVisible;
  P0._accessibleName = accessibleName;
})();
