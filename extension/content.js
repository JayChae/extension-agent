console.log("[AI 신입사원] content script injected on", location.href);

// 백엔드 → SW를 거쳐 온 메시지를 받고 사이드패널로 응답 → 한 바퀴 닫기.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "from_backend") {
    sendResponse({ type: "content_ack", text: "[content@" + location.href + "] " + msg.text });
  }
});
