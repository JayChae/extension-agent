"""Phase 9 자동 검증 — 🔒 횡단 안전 게이트 핵심(가짜 모델 + 가짜 브라우저).

크리티컬 게이트(제출 항상 승인)·도메인 allowlist·레이트 리미터·CAPTCHA 핸드오프·평문 감사 로그를
결정적·무비용으로 돌린다(라이브 모델·실 브라우저 불필요). 헬퍼는 test_loop 재사용.
"""

import json

import audit
import main
import safety
import session as session_mod
from fastapi.testclient import TestClient
from test_loop import drive, model_from, ok_obs

client = TestClient(main.app)

# 제출 버튼이 있는 화면 — "제출"은 CRITICAL_KEYWORDS라 클릭 시 강제 승인 대상.
SUBMIT_SCREEN = ok_obs(elements=['[1]<input name="내용">', '[2]<button name="제출"> 제출'])


# ---- 크리티컬 게이트 — 승인 경로 ----------------------------------------------
def test_critical_gate_approve(monkeypatch):
    steps = [
        ("perceive", {}),
        ("click", {"index": 2}),  # 제출 → 게이트로 런이 멈춘다
        ("done", {"result": "제출 완료"}),
    ]
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: steps[i]))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "제출해줘"})
        assert ws.receive_json()["type"] == "command"  # perceive
        ws.send_json({"type": "observation", "observation": SUBMIT_SCREEN})
        # click(2)=제출 → 실행 안 되고 승인 카드로 종료(성숙도 무관).
        gate = ws.receive_json()
        assert gate["type"] == "approve_action"
        assert "제출" in gate["label"]
        assert gate["index"] == 2
        # 승인 → 도구 본문 재실행 → 진짜 click command가 나간다.
        ws.send_json({"type": "action_approval", "approved": True})
        cmd = ws.receive_json()
        assert cmd["type"] == "command"
        assert cmd["action"]["kind"] == "click" and cmd["action"]["index"] == 2
        ws.send_json({"type": "observation", "observation": ok_obs(note="제출됨")})
        echo = ws.receive_json()
        assert echo["type"] == "backend_echo" and "완료" in echo["text"]


# ---- 크리티컬 게이트 — 거부 경로 ----------------------------------------------
def test_critical_gate_deny(monkeypatch):
    steps = [
        ("perceive", {}),
        ("click", {"index": 2}),  # 제출 → 게이트
        ("done", {"result": "거부되어 중단"}),  # 거부 통보를 받고 모델이 종료
    ]
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: steps[i]))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "제출해줘"})
        assert ws.receive_json()["type"] == "command"  # perceive
        ws.send_json({"type": "observation", "observation": SUBMIT_SCREEN})
        gate = ws.receive_json()
        assert gate["type"] == "approve_action"
        # 거부 → click은 실행되지 않는다(추가 command 없음) → 바로 종료.
        ws.send_json({"type": "action_approval", "approved": False})
        echo = ws.receive_json()
        assert echo["type"] == "backend_echo"


# ---- 도메인 allowlist ----------------------------------------------------------
def test_domain_allowed_unit():
    assert safety.domain_allowed("https://ecfs.scourt.go.kr/x")
    assert safety.domain_allowed("https://scourt.go.kr/")
    assert not safety.domain_allowed("https://evil.com/x")
    assert not safety.domain_allowed("https://scourt.go.kr.evil.com")  # 접미사 위장
    assert not safety.domain_allowed("https://evilscourt.go.kr")  # 점 경계 없음
    assert not safety.domain_allowed("notaurl")


def test_navigate_blocked(monkeypatch):
    # navigate가 거부되면 WS 왕복(command) 없이 모델에 알리고, 모델은 다른 행동으로 종료.
    steps = [
        ("navigate", {"url": "https://evil.com/x"}),
        ("done", {"result": "허용 안 됨 확인"}),
    ]
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: steps[i]))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "딴 사이트 가봐"})
        # 거부는 in-tool이라 command가 안 나간다 → 첫 프레임이 곧 backend_echo여야 한다.
        echo = ws.receive_json()
        assert echo["type"] == "backend_echo" and "완료" in echo["text"]


# ---- 레이트 리미터 ------------------------------------------------------------
def test_rate_limit(monkeypatch):
    monkeypatch.setattr(session_mod, "RATE_MAX", 3)
    monkeypatch.setattr(session_mod, "RATE_WINDOW", 100.0)  # 윈도우 안에 다 들어오게
    # 인덱스 교차로 '같은 동작 반복' 가드 회피, vary로 무진전 회피 → 레이트 리밋이 먼저 걸린다.
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: ("click", {"index": 1 + i % 2})))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "빨리빨리"})
        result = drive(ws, vary=True)
    assert "중단(가드레일)" in result and "레이트 리밋 초과" in result


# ---- CAPTCHA 핸드오프 ----------------------------------------------------------
def test_captcha_handoff(monkeypatch):
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: ("perceive", {})))
    captcha_obs = ok_obs()
    captcha_obs["captcha"] = True
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "로그인"})
        result = drive(ws, observations=[captcha_obs])
    assert "핸드오프" in result and "CAPTCHA" in result


# ---- 평문 감사 로그 ------------------------------------------------------------
def test_audit_log(monkeypatch, tmp_path):
    log_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "LOG_PATH", log_path)
    steps = [
        ("perceive", {}),
        ("type_text", {"index": 1, "text": "2024가단12345"}),  # 비밀값 대역 — 로그에 남으면 안 됨
        ("done", {"result": "ok"}),
    ]
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: steps[i]))
    observations = [ok_obs(elements=['[1]<input name="사건번호">']), ok_obs(note="입력")]
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "사건검색"})
        drive(ws, observations)
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    kinds = {e["event"] for e in events}
    assert "action" in kinds and "observation" in kinds
    # 관측 이벤트는 요약(요소 수)만 — 전체 요소 본문 미기록.
    obs_events = [e for e in events if e["event"] == "observation"]
    assert obs_events and all("n_elements" in e and "elements" not in e for e in obs_events)
    # 입력값(비밀값 대역)은 감사 로그 어디에도 남지 않는다.
    assert all("2024가단12345" not in json.dumps(e, ensure_ascii=False) for e in events)
