// MAIN world 훅(§4) — "content는 얇게(isolated)" 원칙의 *유일한* 예외.
// scourt가 띄우는 네이티브 window.alert/confirm/prompt는 isolated content script가 못 닫는다.
// 페이지 스크립트보다 먼저(run_at:document_start) 가로채 자동 처리하고, 메시지를 CustomEvent로
// isolated content(content.js)에 넘긴다 → 다음 관측에 실려 모델이 무슨 창이 떴는지 본다.
(function () {
  const notify = (kind, message) => {
    try {
      // detail은 문자열로 — MAIN↔ISOLATED 월드 간 객체 클론 문제 회피.
      document.dispatchEvent(
        new CustomEvent("__ai_newbie_dialog__", {
          detail: JSON.stringify({ kind, message: message == null ? "" : String(message) }),
        }),
      );
    } catch {
      /* 전달 실패는 무시 — 다이얼로그 처리 자체는 계속한다 */
    }
  };

  // alert: 알림만(반환값 없음) → 자동으로 사라짐.
  window.alert = function (m) {
    notify("alert", m);
  };
  // confirm: 자동 수락(true). 비가역 클릭은 이미 9A 크리티컬 게이트로 사람이 승인했으므로 안전.
  window.confirm = function (m) {
    notify("confirm", m);
    return true;
  };
  // prompt: 자동 취소(null) — 임의 텍스트를 함부로 채우지 않는다.
  window.prompt = function (m) {
    notify("prompt", m);
    return null;
  };
})();
