chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((err) => console.error(err));
});

// 얇은 라우터: 사이드패널 → 활성 scourt 탭의 content script로 중계. 추론 루프 없음.
const SCOURT_HOST = /(^|\.)scourt\.go\.kr$/;

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  // 사이드패널 → content로 구조화 액션/STOP 중계. (추론 없음)
  if (msg.type === "relay_action") {
    routeToContent({ type: "do_action", action: msg.action }).then(sendResponse);
    return true; // 비동기 sendResponse를 위해 채널 유지
  }
  if (msg.type === "relay_stop") {
    routeToContent({ type: "do_stop" }).then(sendResponse);
    return true;
  }
});

async function routeToContent(payload) {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  let host = "";
  try {
    host = tab && tab.url ? new URL(tab.url).hostname : "";
  } catch {
    host = "";
  }
  if (!tab || !SCOURT_HOST.test(host)) {
    return {
      ok: false,
      error: "활성 scourt 탭이 없습니다 — ecfs.scourt.go.kr 탭을 열어주세요",
    };
  }

  try {
    // all_frames:true 중 최상위 프레임만 — 응답 모호성 제거
    return await chrome.tabs.sendMessage(tab.id, payload, { frameId: 0 });
  } catch (e1) {
    // 두 종류의 실패를 구분한다:
    // ① content script가 아예 없음(익스텐션 로드 전부터 열려 있던 탭) → 1회 주입 후 재시도.
    // ② 클릭이 페이지를 이동시켜 응답 전에 포트가 닫힘 → 액션은 이미 실행됨. 재전송하면
    //    같은 명령이 새 화면(인덱스 비어 있음)으로 다시 가 엉뚱한 에러가 난다 → 재전송 금지.
    const noReceiver = /Receiving end does not exist|Could not establish connection/i.test(
      e1?.message || "",
    );
    if (!noReceiver) {
      return { ok: true, note: "페이지가 이동했어요 — perceive로 새 화면을 다시 읽어주세요." };
    }
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
      return await chrome.tabs.sendMessage(tab.id, payload, { frameId: 0 });
    } catch (e2) {
      return { ok: false, error: "content script 전달 실패: " + e2.message };
    }
  }
}
