// 사이드패널 — WebSocket 소유 + content script 중계. Phase 2 배관(추론 없음).
const log = document.getElementById("log");
const form = document.getElementById("form");
const input = document.getElementById("text");
const stopBtn = document.getElementById("stop");
const teachBtn = document.getElementById("teach");
const statusEl = document.getElementById("status");
const dashboardEl = document.getElementById("dashboard");

const BACKEND_WS = "ws://127.0.0.1:8000/ws";
let ws = null;
let stopped = false;
// "가르치기" 녹화 중이면 {name, events}(행동+설명), 아니면 null.
let recording = null;

function addLine(cls, text) {
  const div = document.createElement("div");
  div.className = "line " + cls;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

// 졸업 대시보드 — SOP 스킬명·성숙도 레벨·최근 성공 추세(O/X 점)를 표시(§10).
// 승급은 자동이라 버튼 없음(표시 전용). promoted면 로그에 축하 한 줄.
function updateDashboard(msg) {
  const name = (msg.path || "").split("/").pop().replace(/\.md$/, "");
  const dots = (msg.success_window || []).map((ok) => (ok ? "●" : "○")).join(" ");
  dashboardEl.querySelector(".skill").textContent = name;
  const levelEl = dashboardEl.querySelector(".level");
  levelEl.textContent = msg.level;
  levelEl.className = "level " + msg.level;
  dashboardEl.querySelector(".dots").textContent = dots;
  dashboardEl.hidden = false;
  if (msg.promoted) {
    addLine("sys", `🎉 승급: ${msg.level} — 이 업무를 점점 잘하게 됐어요`);
  } else if (msg.demoted) {
    addLine("sys", `⚠️ 강등: ${msg.level} — 최근 실패가 늘어 다시 확인이 필요해요`);
  }
}

function connect() {
  if (stopped) return; // STOP 후 예약돼 있던 재연결이 깨어나도 다시 붙지 않게
  ws = new WebSocket(BACKEND_WS);
  ws.onopen = () => {
    statusEl.textContent = "연결됨";
  };
  ws.onclose = () => {
    statusEl.textContent = "연결 끊김 — 5초 후 재연결";
    if (!stopped) setTimeout(connect, 5000);
  };
  ws.onerror = () => {
    statusEl.textContent = "연결 오류 (백엔드가 켜져 있나요?)";
  };
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "backend_echo") {
      addLine("backend", msg.text);
    } else if (msg.type === "command") {
      // 백엔드가 내린 구조화 액션 → content로 중계 → 관측을 백엔드로 되돌림.
      relayAction(msg.action);
    } else if (msg.type === "observation_ack") {
      addLine("backend", msg.text);
    } else if (msg.type === "ask_human") {
      // 에이전트가 막혀서 사수(사람)에게 묻는다 → 질문 카드를 띄우고 답을 기다린다(§6).
      renderAskCard(msg.question, msg.options);
    } else if (msg.type === "propose_sop") {
      // 메모리 에이전트가 시연을 SOP 초안으로 증류했다 → 검토·승인 카드를 띄운다(§7).
      renderSopCard(msg.path, msg.diff, msg.open_branches);
    } else if (msg.type === "propose_lesson") {
      // 막혀서 물은 걸 레슨으로 증류했다 → 화해(ADD/EDIT/STRENGTHEN) 승인 카드를 띄운다(§7 경로②).
      renderLessonCard(msg.path, msg.diff);
    } else if (msg.type === "maturity_update") {
      // 런이 끝나 졸업 카운터가 갱신됐다 → 대시보드에 레벨·성공 추세를 표시(§10).
      updateDashboard(msg);
    } else if (msg.type === "stopped") {
      addLine("sys", "백엔드: 정지됨");
    }
  };
}

// 백엔드 액션을 SW(라우터)를 거쳐 content로 보내고, 관측을 화면 표시 + 백엔드로 송신.
function relayAction(action) {
  chrome.runtime.sendMessage({ type: "relay_action", action }, (obs) => {
    if (chrome.runtime.lastError) {
      addLine("sys", "(content 전달 실패: " + chrome.runtime.lastError.message + ")");
      return;
    }
    addLine("content", formatObservation(obs));
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "observation", observation: obs }));
    }
  });
}

// 관측을 사람이 읽기 좋게 한 덩어리 텍스트로.
function formatObservation(obs) {
  if (!obs) return "(빈 응답)";
  if (!obs.ok) return "✖ " + (obs.error || obs.note || "실패");
  const parts = [];
  if (obs.note) parts.push(obs.note);
  if (obs.elements) parts.push(`요소 ${obs.elements.length}개:\n` + obs.elements.join("\n"));
  if (obs.tables && obs.tables.length) parts.push(`표 ${obs.tables.length}개:\n` + obs.tables.join("\n\n"));
  return parts.join("\n");
}

// 에이전트의 질문을 카드로 띄운다. 옵션은 클릭 버튼, 자유 입력도 허용. 답이 갈 때까지 메인 입력 잠금.
function renderAskCard(question, options) {
  const card = document.createElement("div");
  card.className = "card";

  const head = document.createElement("div");
  head.className = "head";
  const q = document.createElement("div");
  q.className = "q";
  q.textContent = "🙋 " + (question || "(질문 없음)");
  // 닫기: 이 질문은 됐고 다른 일을 시키고 싶을 때. 입력 잠금을 풀고 대기 상태를 비운다.
  const close = document.createElement("button");
  close.type = "button";
  close.className = "close";
  close.textContent = "✕";
  close.title = "질문 닫기";
  close.addEventListener("click", () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "dismiss_question" }));
    }
    addLine("sys", "질문을 닫았습니다 — 다른 요청을 입력하세요.");
    card.remove();
    input.disabled = false;
    input.focus();
  });
  head.appendChild(q);
  head.appendChild(close);
  card.appendChild(head);

  function answer(text) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: "human_answer", text }));
    addLine("user", "답변: " + text);
    card.remove();
    input.disabled = false;
  }

  if (Array.isArray(options) && options.length) {
    const opts = document.createElement("div");
    opts.className = "opts";
    for (const opt of options) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = opt;
      btn.addEventListener("click", () => answer(opt));
      opts.appendChild(btn);
    }
    card.appendChild(opts);
  }

  const ansForm = document.createElement("form");
  ansForm.className = "answer";
  const ansInput = document.createElement("input");
  ansInput.type = "text";
  ansInput.placeholder = "직접 답하기…";
  const ansBtn = document.createElement("button");
  ansBtn.type = "submit";
  ansBtn.textContent = "답변";
  ansForm.appendChild(ansInput);
  ansForm.appendChild(ansBtn);
  ansForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = ansInput.value.trim();
    if (text) answer(text);
  });
  card.appendChild(ansForm);

  input.disabled = true; // 답하기 전엔 메인 입력 잠금(답은 카드로만)
  log.appendChild(card);
  log.scrollTop = log.scrollHeight;
  ansInput.focus();
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || stopped) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    addLine("sys", "(아직 백엔드에 연결되지 않았습니다)");
    return;
  }
  addLine("user", text);
  ws.send(JSON.stringify({ type: "user_input", text }));
  input.value = "";
});

stopBtn.addEventListener("click", () => {
  stopped = true;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "stop" }));
  }
  // content의 실행 직전 취소 플래그도 켠다(§11 "클릭 직전 마지막 취소").
  chrome.runtime.sendMessage({ type: "relay_stop" }, () => void chrome.runtime.lastError);
  resetTeaching();
  // 열려 있던 질문 카드 제거 — 백엔드가 이미 대기 상태를 비워 답이 무시되므로(오해 방지).
  document.querySelectorAll(".card").forEach((c) => c.remove());
  input.disabled = true;
  stopBtn.disabled = true;
  addLine("sys", "STOP — 정지됨");
});

// ───────────────────────── 가르치기(Show me) — 시연 녹화(§7 경로①) ─────────────────────────

// content script가 사람 행동을 기록해 보낸다 → 녹화 중이면 events에 누적(사이드패널은 페이지 이동에도 생존).
chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "record_action" && recording) {
    recording.events.push(msg.record);
    updateTeachStatus();
  }
});

teachBtn.addEventListener("click", () => {
  if (recording) {
    stopTeaching(); // 녹화 중이면 종료·전송
  } else if (!document.getElementById("teach-card")) {
    openTeachCard(); // 업무 이름부터 받는다
  }
});

// 업무 이름 입력 카드 — 사용자 선택: 작은 입력창에 이름 적고 시작.
function openTeachCard() {
  const card = document.createElement("div");
  card.className = "card";
  card.id = "teach-card";

  const head = document.createElement("div");
  head.className = "head";
  const q = document.createElement("div");
  q.className = "q";
  q.textContent = "📝 가르칠 업무의 이름을 적어주세요 (예: 사건검색)";
  const close = document.createElement("button");
  close.type = "button";
  close.className = "close";
  close.textContent = "✕";
  close.addEventListener("click", () => card.remove());
  head.appendChild(q);
  head.appendChild(close);
  card.appendChild(head);

  const f = document.createElement("form");
  f.className = "answer";
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.placeholder = "업무 이름…";
  const startBtn = document.createElement("button");
  startBtn.type = "submit";
  startBtn.textContent = "녹화 시작";
  f.appendChild(nameInput);
  f.appendChild(startBtn);
  f.addEventListener("submit", (e) => {
    e.preventDefault();
    const name = nameInput.value.trim();
    if (name) startTeaching(name, card);
  });
  card.appendChild(f);

  log.appendChild(card);
  log.scrollTop = log.scrollHeight;
  nameInput.focus();
}

function startTeaching(name, card) {
  recording = { name, events: [] };
  chrome.storage.session.set({ recording: true });
  chrome.runtime.sendMessage({ type: "record_start" }, () => void chrome.runtime.lastError);
  teachBtn.textContent = "녹화 종료";
  teachBtn.classList.add("recording");

  // 카드를 "녹화 중" 패널로 바꾼다: 상태 + 설명 추가 입력.
  card.innerHTML = "";
  const q = document.createElement("div");
  q.className = "q";
  q.id = "teach-status";
  card.appendChild(q);

  const noteForm = document.createElement("form");
  noteForm.className = "answer";
  const noteInput = document.createElement("input");
  noteInput.type = "text";
  noteInput.placeholder = "설명 추가 (예: 사건번호는 끝자리까지 정확히)…";
  const noteBtn = document.createElement("button");
  noteBtn.type = "submit";
  noteBtn.textContent = "설명";
  noteForm.appendChild(noteInput);
  noteForm.appendChild(noteBtn);
  noteForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = noteInput.value.trim();
    if (!text || !recording) return;
    recording.events.push({ kind: "note", text });
    noteInput.value = "";
    addLine("sys", "설명 추가: " + text);
    updateTeachStatus();
  });
  card.appendChild(noteForm);

  addLine("sys", `'${name}' 가르치기 시작 — 브라우저에서 직접 해보세요. 설명도 함께 적을 수 있어요.`);
  updateTeachStatus();
  noteInput.focus();
}

function updateTeachStatus() {
  const s = document.getElementById("teach-status");
  if (!s || !recording) return;
  const acts = recording.events.filter((e) => e.kind === "action").length;
  const notes = recording.events.filter((e) => e.kind === "note").length;
  s.textContent = `🔴 녹화 중 — 행동 ${acts}개 · 설명 ${notes}개`;
}

function stopTeaching() {
  const events = recording ? recording.events : [];
  const name = recording ? recording.name : null;
  resetTeaching(); // 녹화 정리(storage 플래그·record_stop 포함)
  if (!events.length) {
    addLine("sys", "녹화된 행동이 없어 취소했어요.");
    return;
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "record_demo", task: name, events }));
    addLine("sys", `시연 종료 — '${name}' 절차를 정리하는 중이에요…`);
  } else {
    addLine("sys", "(백엔드 연결이 없어 시연을 보내지 못했어요)");
  }
}

// 녹화 상태·버튼·카드 초기화 + content 녹화 중단(STOP·종료·취소 공통). storage 플래그를 꼭 끈다 —
// 안 끄면 다음 페이지 이동 때 content가 자가 재시작해 "보이지 않는 녹화"가 남는다.
function resetTeaching() {
  const wasRecording = recording !== null;
  recording = null;
  teachBtn.textContent = "가르치기";
  teachBtn.classList.remove("recording");
  const card = document.getElementById("teach-card");
  if (card) card.remove();
  if (wasRecording) {
    chrome.storage.session.set({ recording: false });
    chrome.runtime.sendMessage({ type: "record_stop" }, () => void chrome.runtime.lastError);
  }
}

// 승인 카드의 diff 표시용 <pre>(SOP 카드·레슨 카드 공용 — 스타일 중복 제거).
function makeDiffPre(diff) {
  const pre = document.createElement("pre");
  pre.textContent = diff || "";
  pre.style.cssText =
    "max-height:220px;overflow:auto;background:#fff;border:1px solid #e0c060;border-radius:4px;padding:6px;font-size:11px;white-space:pre-wrap;word-break:break-all;margin:8px 0;";
  return pre;
}

// 증류된 SOP 초안을 검토·승인하는 카드(§7). 승인 = "배웠다" 순간 + 인젝션 잠금.
function renderSopCard(path, diff, openBranches) {
  const card = document.createElement("div");
  card.className = "card";

  const q = document.createElement("div");
  q.className = "q";
  q.textContent = "📝 새 절차를 배웠어요 — 검토하고 승인하세요\n" + (path || "");
  card.appendChild(q);

  card.appendChild(makeDiffPre(diff));

  // 미해결 분기 — 원하면 지금 설명 추가(승인 시 레슨으로 첨부).
  const branchInputs = [];
  if (Array.isArray(openBranches) && openBranches.length) {
    const wrap = document.createElement("div");
    const label = document.createElement("div");
    label.className = "q";
    label.textContent = "미해결 분기 — 원하면 지금 알려주세요(선택):";
    wrap.appendChild(label);
    for (const b of openBranches) {
      const bi = document.createElement("input");
      bi.type = "text";
      bi.placeholder = b;
      bi.style.cssText = "width:100%;padding:6px;margin:4px 0;box-sizing:border-box;";
      wrap.appendChild(bi);
      branchInputs.push({ branch: b, input: bi });
    }
    card.appendChild(wrap);
  }

  const opts = document.createElement("div");
  opts.className = "opts";
  const approve = document.createElement("button");
  approve.type = "button";
  approve.textContent = "승인 (저장)";
  approve.addEventListener("click", () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const branchNotes = branchInputs
      .filter((b) => b.input.value.trim())
      .map((b) => `${b.branch} → ${b.input.value.trim()}`);
    ws.send(JSON.stringify({ type: "approve_sop", branch_notes: branchNotes }));
    card.remove();
  });
  const reject = document.createElement("button");
  reject.type = "button";
  reject.textContent = "반려";
  reject.addEventListener("click", () => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "reject_sop" }));
    addLine("sys", "절차를 저장하지 않았어요.");
    card.remove();
  });
  opts.appendChild(approve);
  opts.appendChild(reject);
  card.appendChild(opts);

  log.appendChild(card);
  log.scrollTop = log.scrollHeight;
}

// 막혀서 물은 걸 증류한 레슨 변경(ADD/EDIT/STRENGTHEN)을 검토·승인하는 카드(§7 경로②).
function renderLessonCard(path, diff) {
  const card = document.createElement("div");
  card.className = "card";

  const q = document.createElement("div");
  q.className = "q";
  q.textContent = "💡 이번에 알려준 걸 레슨으로 남길까요?\n" + (path || "");
  card.appendChild(q);

  card.appendChild(makeDiffPre(diff));

  const opts = document.createElement("div");
  opts.className = "opts";
  const approve = document.createElement("button");
  approve.type = "button";
  approve.textContent = "승인 (반영)";
  approve.addEventListener("click", () => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "approve_lesson" }));
    card.remove();
  });
  const reject = document.createElement("button");
  reject.type = "button";
  reject.textContent = "반려";
  reject.addEventListener("click", () => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "reject_lesson" }));
    addLine("sys", "레슨을 남기지 않았어요.");
    card.remove();
  });
  opts.appendChild(approve);
  opts.appendChild(reject);
  card.appendChild(opts);

  log.appendChild(card);
  log.scrollTop = log.scrollHeight;
}

connect();
