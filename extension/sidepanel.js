// 사이드패널 — WebSocket 소유 + content script 중계. Phase 2 배관(추론 없음).
const log = document.getElementById("log");
const form = document.getElementById("form");
const input = document.getElementById("text");
const stopBtn = document.getElementById("stop");
const statusEl = document.getElementById("status");

const BACKEND_WS = "ws://127.0.0.1:8000/ws";
let ws = null;
let stopped = false;

function addLine(cls, text) {
  const div = document.createElement("div");
  div.className = "line " + cls;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
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

  const q = document.createElement("div");
  q.className = "q";
  q.textContent = "🙋 " + (question || "(질문 없음)");
  card.appendChild(q);

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
  // 열려 있던 질문 카드 제거 — 백엔드가 이미 대기 상태를 비워 답이 무시되므로(오해 방지).
  document.querySelectorAll(".card").forEach((c) => c.remove());
  input.disabled = true;
  stopBtn.disabled = true;
  addLine("sys", "STOP — 정지됨");
});

connect();
