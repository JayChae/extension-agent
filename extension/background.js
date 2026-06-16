chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((err) => console.error(err));
});

// 얇은 라우터: 사이드패널 → 활성 scourt 탭의 content script로 중계. 추론 루프 없음.
const SCOURT_HOST = /(^|\.)scourt\.go\.kr$/;

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type !== "relay_to_content") return; // 그 외 메시지는 무시
  routeToContent(msg.text).then(sendResponse);
  return true; // 비동기 sendResponse를 위해 채널 유지
});

async function routeToContent(text) {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  let host = "";
  try {
    host = tab && tab.url ? new URL(tab.url).hostname : "";
  } catch {
    host = "";
  }
  if (!tab || !SCOURT_HOST.test(host)) {
    return {
      type: "content_ack",
      text: "(활성 scourt 탭이 없습니다 — ecfs.scourt.go.kr 탭을 열어주세요)",
    };
  }

  const payload = { type: "from_backend", text };
  try {
    // all_frames:true 중 최상위 프레임만 — 응답 모호성 제거
    return await chrome.tabs.sendMessage(tab.id, payload, { frameId: 0 });
  } catch {
    // 익스텐션 로드 전부터 열려 있던 탭은 content script가 아직 없음 →
    // 한 번 주입하고 재시도(사용자가 탭을 새로고침하지 않아도 동작).
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
      return await chrome.tabs.sendMessage(tab.id, payload, { frameId: 0 });
    } catch (e) {
      return { type: "content_ack", text: "(content script 전달 실패: " + e.message + ")" };
    }
  }
}
