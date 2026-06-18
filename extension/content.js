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

// CAPTCHA/안티봇 위젯 감지(§4) — 풀거나 우회하지 않고 백엔드가 사람에게 핸드오프하도록 플래그만 단다.
const CAPTCHA_SELECTORS =
  'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"],' +
  ' .g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]';
function detectCaptcha() {
  return document.querySelector(CAPTCHA_SELECTORS) !== null;
}

// 네이티브 다이얼로그 버퍼(§4) — MAIN world 훅(main_hook.js)이 window.alert/confirm을 가로채
// 자동 처리한 뒤 메시지를 CustomEvent로 보낸다. content는 못 닫으므로 MAIN 예외. 다음 관측에 실어 전달.
let pendingDialogs = [];
document.addEventListener("__ai_newbie_dialog__", (e) => {
  try {
    const d = JSON.parse(e.detail);
    pendingDialogs.push({ kind: d.kind, message: stripMarkers(String(d.message || "")).slice(0, 200) });
    if (pendingDialogs.length > 10) pendingDialogs.shift(); // 폭주 방어
  } catch {
    /* 위조 이벤트 등 — 무시 */
  }
});

// 관측(observation) 한 덩어리. elements/tables가 신뢰 불가 페이지 데이터 채널이다(§3).
// 탈출용 마커 토큰은 위에서 이미 제거(stripMarkers). 실제 <UNTRUSTED_PAGE_DATA> 프롬프트
// 펜스는 모델에 넣는 지점(Phase 4 프롬프트 조립)에서 이 채널을 감싸 적용한다.
function observe(extra) {
  const elements = buildIndex();
  const tables = tablesToMarkdown();
  const obs = Object.assign(
    { ok: true, page: { url: location.href, title: document.title }, elements, tables },
    extra || {},
  );
  // 안전/정보 채널은 마지막에 — extra가 덮지 못하게(§4).
  if (pendingDialogs.length) {
    obs.dialogs = pendingDialogs;
    pendingDialogs = [];
  }
  if (detectCaptcha()) obs.captcha = true;
  return obs;
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

// 화면이 "정착"하면 읽는다 — 고정 대기 대신 DOM 변화가 QUIET 동안 멈출 때까지(MAX 상한 안에서).
// 페이지가 스스로 "다 됐다"고 알리는 셈: 빠른 화면은 빨리, 느린 AJAX는 기다린다(§3 지각 시점).
// content script는 isolated world지만 페이지와 DOM을 공유하므로 페이지발 변화를 본다.
const SETTLE_QUIET_MS = 300; // 이만큼 변화 없으면 정착으로 본다
const SETTLE_MAX_MS = 3000; // 안전 상한 — 끝없이 바뀌는 위젯에도 반드시 반환(끝나면 다음 perceive가 따라잡음)

function settleAndObserve(extra) {
  return new Promise((resolve) => {
    let quiet, cap, observer;
    const finish = () => {
      observer.disconnect();
      clearTimeout(quiet);
      clearTimeout(cap);
      resolve(observe(extra));
    };
    observer = new MutationObserver(() => {
      clearTimeout(quiet); // 변화가 올 때마다 리셋
      quiet = setTimeout(finish, SETTLE_QUIET_MS); // → 변화가 멈춰야 발동
    });
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
    });
    quiet = setTimeout(finish, SETTLE_QUIET_MS); // 처음부터 조용하면 QUIET 후 반환
    cap = setTimeout(finish, SETTLE_MAX_MS); // 안 멈춰도 MAX엔 반드시
  });
}

// ───────────────────────── 문서 열람(PDF) ─────────────────────────
// 문서 링크를 페이지 출처에서 fetch → 로그인·인증서 세션 쿠키가 자동으로 실린다(백엔드 직접 fetch는
// 그 쿠키가 없어 불가). 바이트는 base64로 백엔드에 넘기고 파싱은 백엔드가 한다("content 얇게" §3).
const MAX_DOC_BYTES = 10 * 1024 * 1024; // 10MB 상한 — 백엔드도 같은 상한

// scourt allowlist 호스트인지(파싱 실패=거부). navigate 케이스와 같은 SCOURT_HOST 경계를 쓴다.
function hostAllowed(u) {
  try {
    return SCOURT_HOST.test(new URL(u).hostname);
  } catch {
    return false;
  }
}

async function readDocument(el) {
  const anchor = el.closest && el.closest("a");
  const url = el.href || (anchor && anchor.href) || "";
  if (!url) return { ok: false, error: "직접 링크가 아니에요 — 새 탭/JS 다운로드 문서는 후순위입니다." };
  if (!hostAllowed(url)) return { ok: false, error: `허용 도메인 아님(또는 잘못된 URL): ${url}` };

  let resp;
  try {
    resp = await fetch(url, { credentials: "include" });
  } catch (e) {
    return { ok: false, error: `문서 받기 실패: ${e.message}` };
  }
  if (!resp.ok) return { ok: false, error: `문서 받기 실패: HTTP ${resp.status}` };

  // 리다이렉트가 허용 도메인을 벗어났는지 최종 URL로 재검사 — in-domain 링크가 off-domain으로
  // 302되면 쿠키 유출·공격자 바이트를 신뢰 문서로 파싱하게 된다. source_url도 최종 URL로 보고한다.
  if (!hostAllowed(resp.url)) {
    return { ok: false, error: `리다이렉트가 허용 도메인을 벗어남: ${resp.url}` };
  }

  const buf = await resp.arrayBuffer();
  if (buf.byteLength > MAX_DOC_BYTES) {
    return { ok: false, error: `문서가 너무 큼(${buf.byteLength} bytes, 상한 ${MAX_DOC_BYTES})` };
  }
  return {
    ok: true,
    page: { url: location.href, title: document.title },
    document: {
      source_url: resp.url,
      content_type: resp.headers.get("content-type") || "",
      b64: bytesToBase64(new Uint8Array(buf)),
    },
    note: "문서 받음",
  };
}

// 큰 바이트 배열을 청크로 base64 인코딩(btoa는 한 번에 큰 문자열에서 스택이 터질 수 있음).
function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

async function executeAction(action) {
  // 모든 액션은 실행 직전 STOP 검사(§11 "클릭 직전 마지막 취소").
  if (stopped) return { ok: false, note: "STOP — 취소됨" };
  try {
    switch (action.kind) {
      case "perceive":
        // navigate 후 새 페이지·느린 AJAX를 완료 시점에 읽도록 perceive도 정착 경유(§3).
        return await settleAndObserve();
      case "click":
        doClick(resolve(action.index));
        return await settleAndObserve({ note: `클릭: [${action.index}]` });
      case "type":
        doType(resolve(action.index), action.text || "");
        // 금고가 채운 비밀값(fill_credential)은 note에 echo하지 않는다 — 누출 방지(§11).
        return await settleAndObserve({
          note: action.secret
            ? `입력: [${action.index}] (비밀값)`
            : `입력: [${action.index}] "${action.text || ""}"`,
        });
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
      case "read_document":
        return await readDocument(resolve(action.index));
      default:
        return { ok: false, error: `알 수 없는 액션: ${action.kind}` };
    }
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// ───────────────────────── 녹화(Recording) — "가르치기"(§7 경로①) ─────────────────────────
// 사람이 직접 하는 행동을 역할+이름+텍스트+주변단서+입력값으로 기록(XPath 아님). 비밀값은 블랭킹.
// content는 버퍼를 안 가짐 — 행동마다 사이드패널로 즉시 송신(페이지 이동에 사이드패널은 생존).

let recording = false;

// 텍스트 입력류인지(버튼/체크박스/파일 등 제외) — change에서 type으로 기록할 대상.
function isTextInput(el) {
  if (el.tagName === "TEXTAREA" || el.isContentEditable) return true;
  if (el.tagName !== "INPUT") return false;
  const t = (el.getAttribute("type") || "text").toLowerCase();
  return !["button", "submit", "checkbox", "radio", "hidden", "file", "reset", "image"].includes(t);
}

// 비밀값 필드 — 값 블랭킹(§3·§11). password + 자격증명/인증서 추정 id·name.
function isSensitive(el) {
  if (el.tagName === "INPUT" && (el.getAttribute("type") || "").toLowerCase() === "password") return true;
  const key = ((el.id || "") + " " + (el.getAttribute("name") || "")).toLowerCase();
  return /pass|pwd|pin|secret|cert|인증|비밀/.test(key);
}

// 기록용 역할 문자열 — role 속성 우선, 없으면 태그/타입에서 유도.
function recordRole(el) {
  const role = (el.getAttribute("role") || "").toLowerCase();
  if (role) return role;
  const tag = el.tagName;
  if (tag === "A") return "link";
  if (tag === "BUTTON") return "button";
  if (tag === "SELECT") return "combobox";
  if (tag === "TEXTAREA") return "textbox";
  if (tag === "INPUT") {
    const t = (el.getAttribute("type") || "text").toLowerCase();
    if (t === "button" || t === "submit" || t === "image") return "button";
    if (t === "checkbox") return "checkbox";
    if (t === "radio") return "radio";
    return "textbox";
  }
  return tag.toLowerCase();
}

// 주변 단서 — 감싸는 fieldset legend나 섹션 aria-label(있으면). 최소만.
function nearestCue(el) {
  const fs = el.closest("fieldset");
  if (fs) {
    const lg = fs.querySelector("legend");
    if (lg && lg.textContent.trim()) return stripMarkers(lg.textContent.replace(/\s+/g, " ").trim()).slice(0, 60);
  }
  const sec = el.closest("section,[role=region],[role=dialog],[aria-label]");
  const al = sec && sec.getAttribute("aria-label");
  if (al && al.trim()) return stripMarkers(al.trim()).slice(0, 60);
  return "";
}

// 클릭에서 의미 있는 컨트롤(버튼/링크/체크/라디오/옵션 등)을 조상에서 찾는다. 텍스트입력/select는 제외(change가 담당).
function clickableAncestor(el) {
  for (let p = el; p; p = p.parentElement) {
    const tag = p.tagName;
    if (tag === "TEXTAREA" || tag === "SELECT") return null;
    if (tag === "INPUT") {
      const t = (p.getAttribute("type") || "text").toLowerCase();
      if (["button", "submit", "image", "checkbox", "radio"].includes(t)) return p;
      return null; // 텍스트 입력 클릭은 무시(입력은 change에서)
    }
    if (tag === "BUTTON") return p;
    if (tag === "A" && p.hasAttribute("href")) return p;
    const role = (p.getAttribute("role") || "").toLowerCase();
    if (INTERACTIVE_ROLES.has(role)) return p;
    if (p.hasAttribute("onclick")) return p;
    const cls = p.className && typeof p.className === "string" ? p.className : "";
    if (EXB_INTERACTIVE.test(p.id || "") || EXB_INTERACTIVE.test(cls)) return p;
  }
  return null;
}

function buildRecord(action, el, value) {
  const name = stripMarkers(accessibleName(el));
  return {
    kind: "action",
    action,
    role: recordRole(el),
    name: name.slice(0, 80),
    text: stripMarkers((el.textContent || "").replace(/\s+/g, " ").trim()).slice(0, 80),
    cue: nearestCue(el),
    value: value === undefined ? undefined : String(value).slice(0, 120),
    url: location.href,
    title: document.title,
  };
}

function emitRecord(record) {
  try {
    chrome.runtime.sendMessage({ type: "record_action", record });
  } catch {
    /* 사이드패널이 닫혔으면 무시 */
  }
}

function onClickCapture(e) {
  if (!recording) return;
  const el = clickableAncestor(e.target);
  if (el) emitRecord(buildRecord("click", el, undefined));
}

function onChangeCapture(e) {
  if (!recording) return;
  const el = e.target;
  if (el.tagName === "SELECT") {
    const opt = el.selectedOptions && el.selectedOptions[0];
    emitRecord(buildRecord("select", el, opt ? opt.text.trim() : el.value));
  } else if (isTextInput(el)) {
    const raw = el.isContentEditable ? el.textContent : el.value;
    emitRecord(buildRecord("type", el, isSensitive(el) ? "***" : raw || ""));
  }
}

function startRecording() {
  if (recording) return;
  recording = true;
  document.addEventListener("click", onClickCapture, true);
  document.addEventListener("change", onChangeCapture, true);
}

function stopRecording() {
  recording = false;
  document.removeEventListener("click", onClickCapture, true);
  document.removeEventListener("change", onChangeCapture, true);
}

// 페이지가 이동·재주입돼도 녹화를 이어가기: SW가 열어둔 storage.session 플래그를 보고 자가 시작.
chrome.storage.session.get("recording", (r) => {
  if (chrome.runtime.lastError) return; // 접근수준 미설정 등 — 조용히 통과(녹화 안 함)
  if (r && r.recording) startRecording();
});

// ───────────────────────── 메시징 ─────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "do_action") {
    executeAction(msg.action).then(sendResponse);
    return true; // 비동기 응답
  }
  if (msg.type === "do_stop") {
    stopped = true;
    stopRecording();
    sendResponse({ ok: true, note: "content STOP 플래그 ON" });
  }
  if (msg.type === "do_record_start") {
    startRecording();
    sendResponse({ ok: true, note: "녹화 시작" });
  }
  if (msg.type === "do_record_stop") {
    stopRecording();
    sendResponse({ ok: true, note: "녹화 종료" });
  }
});
