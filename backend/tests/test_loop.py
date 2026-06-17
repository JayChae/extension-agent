"""Phase 4 자동 검증 — 가짜 모델(FunctionModel) + 가짜 브라우저(TestClient WS)로
에이전트 루프와 가드레일 4종을 결정적·무비용으로 돌린다(라이브 Claude·실 브라우저 불필요).

- 모델: main.MODEL을 스크립트 FunctionModel로 교체(컨텍스트var 우회 — TestClient는 별 스레드라
  agent.override가 안 먹는다. 모듈 전역 교체는 모든 스레드에 보인다).
- 브라우저: TestClient websocket이 extension 역할 — command를 받으면 canned observation으로 답한다.
"""

import time
from typing import cast

import main
import session as session_mod
from agent import render_observation
from fastapi import WebSocket
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from session import Session

client = TestClient(main.app)


# ---- 가짜 모델 ----------------------------------------------------------------
def model_from(step_fn):
    """step_fn(i) -> (tool_name, args)를 매 모델 스텝마다 호출해 도구 호출 하나를 낸다."""
    state = {"i": 0}

    def fn(messages, info):
        i = state["i"]
        state["i"] += 1
        name, args = step_fn(i)
        return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args)])

    return FunctionModel(fn)


# ---- 가짜 관측 ----------------------------------------------------------------
def ok_obs(elements=None, tables=None, note=""):
    return {
        "ok": True,
        "page": {"url": "https://ecfs.scourt.go.kr/x", "title": "전자소송"},
        "elements": elements if elements is not None else ['[1]<input name="사건번호">'],
        "tables": tables or [],
        "note": note,
    }


def fail_obs(error="요소 없음"):
    return {"ok": False, "error": error}


def drive(ws, observations=None, vary=False, max_frames=500):
    """extension 흉내: command마다 다음 관측을 회신. 종료 프레임 텍스트를 반환."""
    seq = list(observations or [])
    i = 0
    for _ in range(max_frames):
        msg = ws.receive_json()
        t = msg["type"]
        if t == "command":
            if i < len(seq):
                obs = seq[i]
            elif vary:
                obs = ok_obs(elements=[f"[1]<div> item{i}"])  # 매번 다른 해시 → 무진전 회피
            else:
                obs = ok_obs()
            i += 1
            ws.send_json({"type": "observation", "observation": obs})
        elif t == "backend_echo":
            return msg["text"]
        elif t == "stopped":
            return "STOPPED"
    raise AssertionError("종료 프레임을 못 받음")


# ---- T1: happy path -----------------------------------------------------------
def test_happy_path(monkeypatch):
    steps = [
        ("perceive", {}),
        ("type_text", {"index": 1, "text": "2024가단12345"}),
        ("click", {"index": 2}),
        ("perceive", {}),
        ("done", {"result": "결과표 도달"}),
    ]
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: steps[i]))
    observations = [
        ok_obs(elements=['[1]<input name="사건번호">', '[2]<button name="사건검색"> 사건검색']),
        ok_obs(note="입력 완료"),
        ok_obs(note="클릭"),
        ok_obs(tables=["| 사건번호 |\n| --- |\n| 2024가단12345 |"]),
    ]
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "사건번호 2024가단12345 검색해줘"})
        result = drive(ws, observations)
    assert result.startswith("완료:")
    assert "결과표 도달" in result


# ---- T2: 스텝 예산 -------------------------------------------------------------
def test_step_budget(monkeypatch):
    monkeypatch.setattr(session_mod, "DEFAULT_STEP_BUDGET", 4)
    # 인덱스를 번갈아 → 같은-동작-반복 가드 회피. 관측은 vary로 매번 다른 해시.
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: ("click", {"index": 1 + i % 2})))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "헛돌아라"})
        result = drive(ws, vary=True)
    assert "중단(가드레일)" in result and "스텝 예산 초과" in result


# ---- T3a: 무진전 — 같은 화면 해시 반복 ----------------------------------------
def test_no_progress_same_screen(monkeypatch):
    # perceive(sig None)를 반복 → 같은-동작 가드는 안 걸리고, 동일 관측 해시 반복으로 정지.
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: ("perceive", {})))
    same = ok_obs(elements=["[1]<div> 변화없음"])
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "같은화면"})
        result = drive(ws, observations=[same, same, same, same])
    assert "무진전: 화면 변화 없음" in result


# ---- T3b: 무진전 — 같은 동작 연속 반복 ----------------------------------------
def test_no_progress_same_action(monkeypatch):
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: ("click", {"index": 5})))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "같은동작"})
        result = drive(ws, vary=True)  # 관측은 매번 달라도 click:5 연속이면 정지
    assert "무진전: 같은 동작 반복" in result


# ---- T4: 연속 실패 ------------------------------------------------------------
def test_consecutive_failures(monkeypatch):
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: ("click", {"index": 1 + i})))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "계속실패"})
        result = drive(ws, observations=[fail_obs(), fail_obs(), fail_obs()])
    assert "연속 실패" in result


# ---- T5: 전역 타임아웃 --------------------------------------------------------
def test_wall_clock_timeout(monkeypatch):
    monkeypatch.setattr(session_mod, "WALL_CLOCK_TIMEOUT", 0.0)  # 즉시 만료
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: ("click", {"index": 1 + i})))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "느려터짐"})
        result = drive(ws, vary=True)
    assert "전역 타임아웃" in result


# ---- T6: STOP -----------------------------------------------------------------
def test_stop(monkeypatch):
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: ("perceive", {})))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "작업시작"})
        cmd = ws.receive_json()  # 첫 command(perceive)
        assert cmd["type"] == "command"
        ws.send_json({"type": "stop"})
        msg = ws.receive_json()
        assert msg["type"] == "stopped"


# ---- T8: ask_human → 사람 답 → 무상태 재개 (§6 HITL) --------------------------
def test_ask_human_resume(monkeypatch):
    # 같은 FunctionModel 인스턴스가 두 런(최초+재개)에 걸쳐 호출된다 → state["i"]가 이어진다.
    steps = [
        ("perceive", {}),
        ("ask_human", {"question": "어느 법원을 고를까요?", "options": ["안산지원", "본원"]}),
        ("done", {"result": "안산지원으로 진행 완료"}),
    ]
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: steps[i]))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "사건 검색해줘"})
        cmd = ws.receive_json()  # perceive command
        assert cmd["type"] == "command"
        ws.send_json({"type": "observation", "observation": ok_obs()})
        # ask_human → 런이 DeferredToolRequests로 종료 → 질문 프레임이 온다.
        q = ws.receive_json()
        assert q["type"] == "ask_human"
        assert q["question"] == "어느 법원을 고를까요?"
        assert q["options"] == ["안산지원", "본원"]
        # 사람이 답한다 → 무상태 재개 → done.
        ws.send_json({"type": "human_answer", "text": "안산지원"})
        done = ws.receive_json()
        assert done["type"] == "backend_echo"
        assert done["text"].startswith("완료:") and "안산지원" in done["text"]


# ---- T8b: 질문 닫기(dismiss) → 늦은 답 무시 → 새 작업 정상 시작 ---------------
def test_dismiss_question(monkeypatch):
    steps = [
        ("perceive", {}),
        ("ask_human", {"question": "법원?", "options": None}),
        ("done", {"result": "재시작 완료"}),  # 닫은 뒤 새 user_input으로 시작되는 런이 도달
    ]
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: steps[i]))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "t1"})
        assert ws.receive_json()["type"] == "command"  # perceive
        ws.send_json({"type": "observation", "observation": ok_obs()})
        assert ws.receive_json()["type"] == "ask_human"
        # 질문을 닫는다 → 대기 상태가 비워져, 뒤늦은 답은 무시되고(재개 안 됨)
        ws.send_json({"type": "dismiss_question"})
        ws.send_json({"type": "human_answer", "text": "무시될 답"})
        # 새 요청은 깨끗이 시작된다
        ws.send_json({"type": "user_input", "text": "t2"})
        result = drive(ws)
    assert result.startswith("완료:") and "재시작 완료" in result


# ---- T9: resume()는 steps 보존 + wall-clock 리셋 ------------------------------
def test_resume_preserves_steps_resets_clock():
    s = Session(ws=cast(WebSocket, None))  # 이 테스트는 resume() 로직만 검증 — ws를 안 쓴다
    s.reset()
    s.steps = 5
    s.last_tool_sig = "click:5"
    s.started_at = time.monotonic() - 1000.0  # 사람이 오래 기다린 척
    s.resume()
    assert s.steps == 5  # 전체 작업량 제한은 유지(보존)
    assert time.monotonic() - s.started_at < 1.0  # 타임아웃 시계만 새로 시작
    assert s.last_tool_sig is None  # 답 직후 같은 동작이 와도 무진전 가드에 안 걸리게 비움


# ---- T7: 펜스(프롬프트 인젝션 격리) -------------------------------------------
def test_fence_wraps_observation():
    fenced = render_observation(ok_obs(elements=["[1]<button> 클릭"]))
    assert fenced.startswith("<UNTRUSTED_PAGE_DATA>")
    assert fenced.endswith("</UNTRUSTED_PAGE_DATA>")
    assert "[1]<button> 클릭" in fenced
    # 실패 관측도 펜스 안에
    f2 = render_observation(fail_obs("허용 도메인 아님"))
    assert "<UNTRUSTED_PAGE_DATA>" in f2 and "허용 도메인 아님" in f2
