/*
 * Phase 0 — oracle.js
 * MAIN-world jQuery "정답지(answer key)".
 *
 * 페이지 자신의 jQuery 이벤트 레지스트리를 읽어, 실제로 click 계열 핸들러가 붙은
 * 요소를 전부 열거한다. scourt 버튼의 핸들러는 대부분 jQuery 로 붙어 있어서,
 * isolated-world content script 의 간접 신호로는 안 보인다. 이 oracle 은 "진짜로
 * 클릭되는 게 무엇인지"를 알려주는 채점용 답안지일 뿐 — 운영 메커니즘이 아니다.
 *
 * 직접 바인딩(per-element) 과 위임(delegation, $(root).on('click','.sel',..)) 을
 * 모두 잡고, 어느 쪽이 우세한지(bindingStyle)도 보고한다. 위임이 우세하면 요소별
 * 핸들러 탐지 자체가 불안정하다는 신호 — 지각 설계를 더 크게 바꿔야 한다.
 */
(function () {
  const P0 = (window.__P0 = window.__P0 || {});
  const CLICKISH = new Set(['click', 'mousedown', 'mouseup', 'keydown']);

  function getJQ(win) {
    return win.jQuery || win.$ || null;
  }

  function jqueryOracle(doc, win) {
    const $ = getJQ(win);
    if (!$ || !$.fn) return { available: false, reason: 'no jQuery on this frame' };
    const version = $.fn.jquery || '?';

    const readEvents = function (node) {
      try {
        if ($._data) return $._data(node, 'events'); // jQuery 1.8+
        if ($.data) return $.data(node, 'events'); // 구버전 폴백
      } catch (e) {}
      return null;
    };

    const all = Array.from(doc.querySelectorAll('*'));

    // 1) 위임 규칙 수집: selector 가 있는 핸들러를 모은다 (root 는 보통 document/body)
    const delegatedRules = []; // {root, type, selector}
    const roots = all.concat([doc, doc.documentElement, doc.body].filter(Boolean));
    for (const root of roots) {
      const ev = readEvents(root);
      if (!ev) continue;
      for (const type of Object.keys(ev)) {
        if (!CLICKISH.has(type)) continue;
        for (const h of ev[type]) {
          if (h && h.selector) delegatedRules.push({ root, type, selector: h.selector });
        }
      }
    }

    // 2) 요소별 판정 → Map(el -> {direct, delegated, types:Set})
    const map = new Map();
    const mark = function (el, kind, type) {
      let rec = map.get(el);
      if (!rec) { rec = { direct: false, delegated: false, types: new Set() }; map.set(el, rec); }
      rec[kind] = true;
      rec.types.add(type);
    };

    // 2a) 직접 바인딩 (selector 없는 핸들러)
    for (const el of all) {
      const ev = readEvents(el);
      if (!ev) continue;
      for (const type of Object.keys(ev)) {
        if (!CLICKISH.has(type)) continue;
        if (ev[type].some((h) => h && !h.selector)) mark(el, 'direct', type);
      }
    }

    // 2b) 위임 매칭 (root 의 후손이면서 selector 에 매치되는 요소)
    for (const el of all) {
      for (const rule of delegatedRules) {
        try {
          if (rule.root.contains && rule.root.contains(el) && el.matches(rule.selector)) {
            mark(el, 'delegated', rule.type);
          }
        } catch (e) {}
      }
    }

    let directCount = 0, delegatedCount = 0;
    for (const rec of map.values()) {
      if (rec.direct) directCount++;
      if (rec.delegated) delegatedCount++;
    }
    const bindingStyle =
      delegatedCount > directCount ? 'delegated'
        : directCount > 0 ? 'per-element'
          : 'none';

    return {
      available: true,
      version,
      map,
      directCount,
      delegatedCount,
      delegatedRuleCount: delegatedRules.length,
      bindingStyle,
    };
  }

  P0.jqueryOracle = jqueryOracle;
})();
