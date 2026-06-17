"""Phase 8 자동 검증 — "점점 나아진다"(증거 기반 졸업)를
가짜 모델(FunctionModel) + 임시 git repo + TestClient WS로 결정적·무비용 검증한다.

검증(§13 Phase 8): SOP 라우팅 런 종료 → 별도 심판이 최종 화면으로 성공 판정(자기선언 금지) →
maturity.success_window 누적 → 검증된 성공률 ≥ 0.9면 LEARNING→ASSISTED 자동 승급 → 대시보드(maturity_update) 표시.
"""

import subprocess

import main
import memory_agent as ma_mod
import memory_store
from fastapi.testclient import TestClient
from memory_agent import SopDraft, VerifyVerdict
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from test_learning import SOP_DICT, setup_temp_repo
from test_lessons import _teach_sop
from test_loop import drive, model_from, ok_obs

client = TestClient(main.app)

SOP_PATH = "ecfs.scourt.go.kr/사건검색.md"
PASS_VERDICT = {"must_appear": True, "must_match": True, "must_not": True, "evidence": "결과표에 사건번호 일치"}


def verify_model(verdict):
    """심판(verify_agent) 대역 — output 도구 final_result로 VerifyVerdict를 낸다."""

    def fn(messages, info):
        return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=verdict)])

    return FunctionModel(fn)


def _perceive_then_done_model():
    """스텝 루프 대역 — 관측(도구 반환)이 아직 없으면 perceive, 있으면 done.

    전역 카운터가 아니라 런별 message_history로 판단 → 한 연결에서 여러 런을 돌려도 매번 perceive→done."""

    def fn(messages, info):
        has_obs = any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts)
        if has_obs:
            return ModelResponse(parts=[ToolCallPart(tool_name="done", args={"result": "조회 완료"})])
        return ModelResponse(parts=[ToolCallPart(tool_name="perceive", args={})])

    return FunctionModel(fn)


def _run_routed(ws):
    """SOP로 라우팅되는 한 런(perceive→done)을 돌리고 maturity_update 프레임을 돌려준다."""
    ws.send_json({"type": "user_input", "text": "사건 조회해줘"})
    cmd = ws.receive_json()
    assert cmd["type"] == "command"  # perceive
    ws.send_json(
        {"type": "observation", "observation": ok_obs(tables=["| 사건번호 |\n|---|\n| 2024가단12345 |"])}
    )
    echo = ws.receive_json()
    assert echo["type"] == "backend_echo" and echo["text"].startswith("완료:")
    mat = ws.receive_json()
    assert mat["type"] == "maturity_update"
    return mat


# ── 단위: record_outcome 승급/강등 ─────────────────────────────────────────────


def test_record_outcome_promote_and_demote(tmp_path, monkeypatch):
    """9/10 검증 성공 → LEARNING→ASSISTED 승급. 이후 성공률 0.9 미만 → 강등."""
    setup_temp_repo(tmp_path, monkeypatch)
    memory_store.approve("ecfs.scourt.go.kr", "사건검색", SopDraft.model_validate(SOP_DICT))

    # 9번 성공 누적 — 창이 10에 못 차 아직 LEARNING(꽉 찬 창에서만 판정)
    for _ in range(9):
        res = memory_store.record_outcome(SOP_PATH, True)
    assert res["level"] == "LEARNING" and res["promoted"] is False

    # 10번째(9성공+1실패=0.9) → 승급
    res = memory_store.record_outcome(SOP_PATH, False)
    assert res["level"] == "ASSISTED" and res["promoted"] is True
    assert sum(1 for x in res["success_window"] if x) == 9 and len(res["success_window"]) == 10

    # 강등: 한 번 더 실패 → 창 [8성공/10] = 0.8 < 0.9 → LEARNING
    res = memory_store.record_outcome(SOP_PATH, False)
    assert res["level"] == "LEARNING" and res["demoted"] is True


def test_record_outcome_preserves_body(tmp_path, monkeypatch):
    """maturity 갱신은 프론트매터만 손대고 본문(## 순서/## 레슨/사람 tail)을 글자 그대로 보존한다."""
    repo, mem = setup_temp_repo(tmp_path, monkeypatch)
    memory_store.approve("ecfs.scourt.go.kr", "사건검색", SopDraft.model_validate(SOP_DICT), ["기존 레슨"])
    sop_file = mem / "sop" / "ecfs.scourt.go.kr" / "사건검색.md"
    sop_file.write_text(
        sop_file.read_text(encoding="utf-8") + "\n## 사람 메모\n자유 메모\n", encoding="utf-8"
    )
    memory_store.record_outcome(SOP_PATH, True)
    content = sop_file.read_text(encoding="utf-8")
    assert "## 순서" in content and "## 레슨" in content  # 본문 보존
    assert "## 사람 메모" in content and "자유 메모" in content  # tail 보존
    assert "기존 레슨" in content and "{사건번호}" in content
    assert "success_window:" in content  # maturity 갱신됨

    # 커밋은 SOP 파일만 건드림(인덱스 안 건드림)
    names = subprocess.run(
        ["git", "-c", "core.quotepath=false", "show", "--name-only", "--pretty=format:", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert names == ["memory/sop/ecfs.scourt.go.kr/사건검색.md"]


# ── 단위: _verify_passed 결정적 규칙(≥2/4 전부 통과) ──────────────────────────


def test_verify_passed_rule():
    full = {"must_appear": ["a"], "must_match": ["b"], "must_not": ["c"], "artifact": []}
    assert main._verify_passed(full, VerifyVerdict(must_appear=True, must_match=True, must_not=True, evidence="ok"))
    # 한 종류라도 실패 → 실패
    assert not main._verify_passed(full, VerifyVerdict(must_appear=True, must_match=False, must_not=True, evidence="x"))
    # 채워진 종류 <2 → 약한 verify, 졸업 금지
    one = {"must_appear": ["a"], "must_match": [], "must_not": [], "artifact": []}
    assert not main._verify_passed(one, VerifyVerdict(must_appear=True, evidence="x"))
    # artifact가 채워졌으면 MVP 미평가 → 보수적 실패
    art = {"must_appear": ["a"], "must_match": ["b"], "must_not": [], "artifact": ["file.pdf"]}
    assert not main._verify_passed(art, VerifyVerdict(must_appear=True, must_match=True, evidence="x"))


# ── 풀루프: verify → 졸업 → 대시보드 ──────────────────────────────────────────


def test_fullloop_verify_promotes_to_assisted(tmp_path, monkeypatch):
    """SOP 라우팅 런 10회(심판 통과) → success_window 누적 → 10회째 LEARNING→ASSISTED 승급 표시."""
    setup_temp_repo(tmp_path, monkeypatch)
    _teach_sop(monkeypatch)  # 라우팅 대상 SOP 학습(증류 모델 사용)
    monkeypatch.setattr(main, "MODEL", _perceive_then_done_model())
    monkeypatch.setattr(ma_mod, "MEMORY_MODEL", verify_model(PASS_VERDICT))  # 심판 통과

    with client.websocket_connect("/ws") as ws:
        levels = [_run_routed(ws) for _ in range(10)]

    assert all(m["level"] == "LEARNING" and m["promoted"] is False for m in levels[:9])
    last = levels[9]
    assert last["level"] == "ASSISTED" and last["promoted"] is True
    assert last["success"] is True and len(last["success_window"]) == 10

    # 파일 프론트매터에 ASSISTED 기록됨(다음 런이 그 레벨을 읽는다)
    content = (memory_store.MEMORY_DIR / "sop" / "ecfs.scourt.go.kr" / "사건검색.md").read_text(
        encoding="utf-8"
    )
    assert "level: ASSISTED" in content


def test_fullloop_verify_fail_counts_as_failure(tmp_path, monkeypatch):
    """심판이 기준 미충족으로 판정 → success=False로 집계(졸업 안 됨)."""
    setup_temp_repo(tmp_path, monkeypatch)
    _teach_sop(monkeypatch)
    monkeypatch.setattr(main, "MODEL", _perceive_then_done_model())
    fail_verdict = {"must_appear": True, "must_match": False, "must_not": True, "evidence": "사건번호 불일치"}
    monkeypatch.setattr(ma_mod, "MEMORY_MODEL", verify_model(fail_verdict))

    with client.websocket_connect("/ws") as ws:
        mat = _run_routed(ws)
    assert mat["success"] is False and mat["level"] == "LEARNING" and mat["promoted"] is False


def test_guardrail_halt_counts_as_failure(tmp_path, monkeypatch):
    """가드레일 중단(무진전)으로 끝난 라우팅 런 → 화면 판정 없이 success=False로 집계(§10 강등 신호)."""
    setup_temp_repo(tmp_path, monkeypatch)
    _teach_sop(monkeypatch)
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: ("click", {"index": 5})))  # 같은 동작 반복

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "사건 조회해줘"})
        result = drive(ws, vary=True)  # backend_echo(중단)에서 반환
        assert "무진전" in result
        mat = ws.receive_json()
    assert mat["type"] == "maturity_update" and mat["success"] is False
