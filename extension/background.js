chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((err) => console.error(err));
});

// content script가 storage.session의 "recording" 플래그를 읽을 수 있게 한다(녹화 자가 시작용, §7).
// 기본 접근수준은 신뢰 컨텍스트 전용이라 content엔 안 보임 → 확장해 준다.
function allowContentSessionAccess() {
  chrome.storage.session
    .setAccessLevel({ accessLevel: "TRUSTED_AND_UNTRUSTED_CONTEXTS" })
    .catch((err) => console.error(err));
}
chrome.runtime.onInstalled.addListener(allowContentSessionAccess);
chrome.runtime.onStartup.addListener(allowContentSessionAccess);

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
  // "가르치기" 녹화 시작/종료를 현재 scourt 탭의 content로 중계(§7). storage 플래그는 사이드패널이 세팅.
  if (msg.type === "record_start") {
    routeToContent({ type: "do_record_start" }).then(sendResponse);
    return true;
  }
  if (msg.type === "record_stop") {
    routeToContent({ type: "do_record_stop" }).then(sendResponse);
    return true;
  }
  // record_action(content→사이드패널)은 SW가 처리하지 않는다 — 사이드패널이 직접 받는다.
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
