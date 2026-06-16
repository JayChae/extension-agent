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
      relayToContent(msg.text); // 백엔드 → content script 한 바퀴
    } else if (msg.type === "stopped") {
      addLine("sys", "백엔드: 정지됨");
    }
  };
}

// 백엔드가 돌려준 메시지를 SW(라우터)를 거쳐 content script로 보내고, 그 응답을 표시.
function relayToContent(text) {
  chrome.runtime.sendMessage({ type: "relay_to_content", text }, (reply) => {
    if (chrome.runtime.lastError) {
      addLine("sys", "(content 전달 실패: " + chrome.runtime.lastError.message + ")");
      return;
    }
    if (reply && reply.text) addLine("content", reply.text);
  });
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
  input.disabled = true;
  stopBtn.disabled = true;
  addLine("sys", "STOP — 정지됨");
});

connect();
