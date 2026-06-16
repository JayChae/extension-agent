console.log("[AI 신입사원] content script injected on", location.href);

// Phase 3 — "손과 눈": 화면을 인덱스 목록으로 읽고(지각), 인덱스로 클릭/입력한다(행동).
// 셀렉터를 만들지 않는다(§4) — 현재 스냅샷의 indexMap[인덱스]→실제 노드로만 조작.

// 현재 스냅샷: 인덱스 → DOM 노드. buildIndex()마다 새로 채운다.
let indexMap = [];
// 직전 스냅샷의 요소 시그니처(새로 생긴 요소에 * 마커를 달기 위함).
let prevSignatures = new Set();
// STOP 킬스위치 — 켜지면 모든 액션을 실행 직전 취소(§11).
let stopped = false;

// ───────────────────────── 지각(Perception) ─────────────────────────

// eXBuilder6 상호작용 컨트롤 접두사(§3). _grd_(표 뼈대)는 일부러 제외.
const EXB_INTERACTIVE = /_(btn|ibx|sbx|acp|rad|chk)_/;
// 인덱스에서 제외할 컨테이너성 태그.
const SKIP_TAGS = new Set(["HTML", "BODY", "SCRIPT", "STYLE", "NOSCRIPT", "META", "LINK", "HEAD"]);
const INTERACTIVE_ROLES = new Set([
  "button", "link", "checkbox", "radio", "tab", "menuitem", "menuitemcheckbox",
  "menuitemradio", "option", "switch", "textbox", "combobox", "searchbox",
]);

// 보이면 계산된 스타일을 반환, 아니면 null. 반환 스타일을 재사용해 getComputedStyle 중복 호출 방지.
function visibleStyle(el) {
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return null;
  const style = getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return null;
  return style;
}

// 페이지 콘텐츠가 격리 마커를 위조해 탈출하지 못하게 토큰 제거(§3 인젝션 저항).
function stripMarkers(text) {
  return text.replace(/<\/?UNTRUSTED_PAGE_DATA>/gi, "");
}

// 강한 신호(§3) — "이게 진짜 컨트롤이다": 네이티브 태그 / ARIA 역할 / eXBuilder6 접두사.
function isStrong(el) {
  const tag = el.tagName;
  if (tag === "BUTTON" || tag === "SELECT" || tag === "TEXTAREA") return true;
  if (tag === "A" && el.hasAttribute("href")) return true;
  if (tag === "INPUT") {
    const type = (el.getAttribute("type") || "text").toLowerCase();
    return type !== "hidden";
  }
  const role = (el.getAttribute("role") || "").toLowerCase();
  if (INTERACTIVE_ROLES.has(role)) return true;
  const id = el.id || "";
  const cls = el.className && typeof el.className === "string" ? el.className : "";
  return EXB_INTERACTIVE.test(id) || EXB_INTERACTIVE.test(cls);
}

// 약한 신호 — 래퍼 div에도 잘 붙음(cursor:pointer는 자식에 상속). 강한 컨트롤이 곁에 없을 때만 쓴다.
// cursor는 호출부가 이미 구한 style을 넘겨받아 판정(중복 getComputedStyle 방지).
function isWeakSignal(el, style) {
  if (el.hasAttribute("aria-expanded") || el.hasAttribute("aria-pressed")) return true;
  if (el.hasAttribute("onclick")) return true;
  const tabindex = el.getAttribute("tabindex");
  if (tabindex !== null && Number(tabindex) >= 0) return true;
  return style.cursor === "pointer";
}

function isDisabled(el) {
  return el.disabled === true || el.getAttribute("aria-disabled") === "true";
}

// 접근가능 이름: aria-label → 연결 label → placeholder → 보이는 텍스트 → title → value 순.
function accessibleName(el) {
  const aria = el.getAttribute("aria-label");
  if (aria && aria.trim()) return aria.trim();
  if (el.id) {
    const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    if (label && label.textContent.trim()) return label.textContent.trim();
  }
  const ph = el.getAttribute("placeholder");
  if (ph && ph.trim()) return ph.trim();
  const text = (el.textContent || "").replace(/\s+/g, " ").trim();
  if (text) return text;
  const title = el.getAttribute("title");
  if (title && title.trim()) return title.trim();
  // 입력값(.value)은 관측에 절대 싣지 않는다 — 인덱스로 행동하므로 현재값 불필요,
  // 비밀번호·주민번호 등 민감값 누출 방지(§3·§11). 식별은 label/placeholder로 충분.
  return "";
}

// 요소의 안정적 식별 시그니처(* 새 요소 마커용). 위치가 아니라 태그+이름+id 기반.
function signatureOf(el, name) {
  return `${el.tagName}|${el.id || ""}|${(el.getAttribute("name") || "")}|${name.slice(0, 40)}`;
}

// 화면을 컴팩트 인덱스 목록으로 만든다. indexMap을 갱신하고 줄 배열을 반환.
function buildIndex() {
  // 후보 수집 — 요소당 getComputedStyle 1회만(가시성+커서 신호 공유).
  const all = [];
  for (const el of document.querySelectorAll("*")) {
    if (SKIP_TAGS.has(el.tagName) || isDisabled(el)) continue;
    const style = visibleStyle(el);
    if (!style) continue;
    if (isStrong(el) || isWeakSignal(el, style)) all.push(el);
  }
  const candidateSet = new Set(all);
  const strongSet = new Set(all.filter(isStrong));

  // 강한 컨트롤을 감싼 후보(=강한 자손을 가진 후보)를 조상 walk로 표시 — O(n·깊이).
  const wrapsStrong = new Set();
  for (const s of strongSet) {
    for (let p = s.parentElement; p; p = p.parentElement) {
      if (candidateSet.has(p)) wrapsStrong.add(p);
    }
  }

  // 컨테이너 dedup — 강: 가장 안쪽만 / 약: 강 래퍼·내부·약 중첩 제외(가장 바깥만).
  const leaves = all.filter((el) => {
    if (strongSet.has(el)) return !wrapsStrong.has(el);
    if (wrapsStrong.has(el)) return false;
    for (let p = el.parentElement; p; p = p.parentElement) {
      if (candidateSet.has(p)) return false; // 후보 조상이 있으면 바깥 것에 양보
    }
    return true;
  });

  indexMap = [];
  const lines = [];
  const signatures = new Set();
  let i = 0;
  for (const el of leaves) {
    const name = stripMarkers(accessibleName(el));
    const sig = signatureOf(el, name);
    signatures.add(sig);
    const isNew = prevSignatures.size > 0 && !prevSignatures.has(sig);
    const tag = el.tagName.toLowerCase();
    const attr =
      el.getAttribute("name") || (el.id ? "#" + el.id : "") || el.getAttribute("role") || "";
    const attrStr = attr ? ` name="${attr.slice(0, 40)}"` : "";
    lines.push(`${isNew ? "*" : ""}[${i}]<${tag}${attrStr}> ${name.slice(0, 80)}`.trim());
    indexMap.push(el);
    i++;
  }
  prevSignatures = signatures;
  return lines;
}

// 표(_grd_ 등) → Markdown(§3). 각 행 텍스트 보존 → 모델이 텍스트로 행 매칭.
function tablesToMarkdown() {
  const tables = Array.from(document.querySelectorAll("table")).filter((t) => visibleStyle(t));
  const out = [];
  for (const table of tables) {
    const rows = Array.from(table.querySelectorAll("tr")).filter((r) => visibleStyle(r));
    if (rows.length === 0) continue;
    const md = [];
    let headerDone = false;
    for (const row of rows.slice(0, 50)) {
      // 행 수 상한
      const cells = Array.from(row.querySelectorAll("th, td"));
      if (cells.length === 0) continue;
      const texts = cells.map((c) => stripMarkers((c.textContent || "").replace(/\s+/g, " ").trim()));
      md.push("| " + texts.join(" | ") + " |");
      if (!headerDone) {
        md.push("| " + cells.map(() => "---").join(" | ") + " |");
        headerDone = true;
      }
    }
    if (md.length > 1) out.push(md.join("\n"));
  }
  return out;
}

// 관측(observation) 한 덩어리. elements/tables가 신뢰 불가 페이지 데이터 채널이다(§3).
// 탈출용 마커 토큰은 위에서 이미 제거(stripMarkers). 실제 <UNTRUSTED_PAGE_DATA> 프롬프트
// 펜스는 모델에 넣는 지점(Phase 4 프롬프트 조립)에서 이 채널을 감싸 적용한다.
function observe(extra) {
  const elements = buildIndex();
  const tables = tablesToMarkdown();
  return Object.assign(
    { ok: true, page: { url: location.href, title: document.title }, elements, tables },
    extra || {},
  );
}

// ───────────────────────── 행동(Action) ─────────────────────────

function resolve(index) {
  const el = indexMap[index];
  if (!el) throw new Error(`인덱스 ${index} 없음 — 먼저 perceive로 화면을 읽으세요`);
  // 직전 perceive 이후 DOM이 바뀌어 노드가 분리됐으면 stale — 다시 읽게 한다.
  if (!el.isConnected) throw new Error(`인덱스 ${index} 만료(화면 변경) — perceive로 다시 읽으세요`);
  return el;
}

function doClick(el) {
  el.scrollIntoView({ block: "center" });
  // 합성 클릭(scourt는 isTrusted=false 수용 — 레거시 RPA로 확인).
  for (const type of ["mousedown", "mouseup", "click"]) {
    el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
  }
  if (typeof el.click === "function") el.click();
}

function doType(el, text) {
  // 값 설정이 무효인 비입력 요소에 조용히 "성공"하지 않도록 가드.
  const editable = el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable;
  if (!editable) throw new Error(`type 불가 — 입력 요소가 아님(<${el.tagName.toLowerCase()}>)`);
  el.focus();
  if (el.isContentEditable) {
    el.textContent = text;
  } else {
    el.value = text;
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function doSelect(el, option) {
  if (el.tagName !== "SELECT") throw new Error("select는 <select> 요소에만 가능");
  const opts = Array.from(el.options);
  const match = opts.find((o) => o.text.trim() === option || o.value === option);
  if (!match) throw new Error(`옵션 "${option}" 없음`);
  el.value = match.value;
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

// 도메인 allowlist(§11). background.js·manifest.json에도 같은 범위가 있으니 함께 갱신할 것
// (MV3 content/SW 런타임 분리로 모듈 공유 불가 — 향후 설정값화 시 일원화).
const SCOURT_HOST = /(^|\.)scourt\.go\.kr$/;

// 짧은 정착 지연 후 새 관측을 반환(AJAX/모달 반영 시간).
function settleAndObserve(extra) {
  return new Promise((resolve) => {
    setTimeout(() => resolve(observe(extra)), 350);
  });
}

async function executeAction(action) {
  // 모든 액션은 실행 직전 STOP 검사(§11 "클릭 직전 마지막 취소").
  if (stopped) return { ok: false, note: "STOP — 취소됨" };
  try {
    switch (action.kind) {
      case "perceive":
        return observe();
      case "click":
        doClick(resolve(action.index));
        return await settleAndObserve({ note: `클릭: [${action.index}]` });
      case "type":
        doType(resolve(action.index), action.text || "");
        return await settleAndObserve({ note: `입력: [${action.index}] "${action.text || ""}"` });
      case "select":
        doSelect(resolve(action.index), action.option || "");
        return await settleAndObserve({ note: `선택: [${action.index}] "${action.option || ""}"` });
      case "navigate": {
        let host = "";
        try {
          host = new URL(action.url).hostname;
        } catch {
          return { ok: false, error: `잘못된 URL: ${action.url}` };
        }
        if (!SCOURT_HOST.test(host)) return { ok: false, error: `허용 도메인 아님: ${host}` };
        location.href = action.url;
        return { ok: true, note: `이동: ${action.url}` };
      }
      case "scroll":
        window.scrollBy(0, action.dir === "up" ? -window.innerHeight : window.innerHeight);
        return await settleAndObserve({ note: `스크롤: ${action.dir || "down"}` });
      case "extract":
        return observe({ note: `추출: ${action.query || ""}` });
      default:
        return { ok: false, error: `알 수 없는 액션: ${action.kind}` };
    }
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// ───────────────────────── 메시징 ─────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "do_action") {
    executeAction(msg.action).then(sendResponse);
    return true; // 비동기 응답
  }
  if (msg.type === "do_stop") {
    stopped = true;
    sendResponse({ ok: true, note: "content STOP 플래그 ON" });
  }
});
