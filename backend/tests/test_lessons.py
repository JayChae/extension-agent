"""Phase 7 자동 검증 — "교정으로 배운다"(레슨 누적 + 화해)를
가짜 모델(FunctionModel) + 임시 git repo + TestClient WS로 결정적·무비용 검증한다.

검증(§13 Phase 7): SOP 따라 일하다 막혀 물음(ask_human) → 사람 답 → 런 종료 시 레슨 증류(propose_lesson)
→ 승인(approve_lesson) → 화해(ADD/EDIT/STRENGTHEN) 병합 + git 커밋 → 다음 런에서 read_sop가 그 레슨을 로드.
"""

import subprocess

import agent as agent_mod
import main
import memory_agent as ma_mod
import memory_store
from fastapi.testclient import TestClient
from memory_agent import LessonOp, SopDraft
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from test_learning import SOP_DICT, distiller_model, setup_temp_repo

client = TestClient(main.app)

LESSON_TEXT = "사건번호는 끝자리까지 완전 일치 행만 선택"


def lesson_model(ops):
    """레슨 증류(lesson_agent) 대역 — output 도구 final_result로 LessonProposal(ops)을 낸다."""

    def fn(messages, info):
        return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args={"ops": ops})])

    return FunctionModel(fn)


def _ask_then_done_model():
    """스텝 루프 대역 — 첫 호출은 ask_human, (사람 답 후) 재개 호출은 done."""
    state = {"i": 0}

    def fn(messages, info):
        i = state["i"]
        state["i"] += 1
        if i == 0:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="ask_human", args={"question": "이 행을 읽을까요?"})]
            )
        return ModelResponse(parts=[ToolCallPart(tool_name="done", args={"result": "조회 완료"})])

    return FunctionModel(fn)


def _teach_sop(monkeypatch):
    """라우팅 대상 SOP를 한 번 가르쳐 둔다(시연→증류→승인)."""
    monkeypatch.setattr(ma_mod, "MEMORY_MODEL", distiller_model())
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "type": "record_demo",
                "task": "사건검색",
                "events": [
                    {
                        "kind": "action",
                        "action": "click",
                        "role": "button",
                        "name": "검색",
                        "url": "https://ecfs.scourt.go.kr/p",
                    }
                ],
            }
        )
        assert ws.receive_json()["type"] == "propose_sop"
        ws.send_json({"type": "approve_sop"})
        assert ws.receive_json()["type"] == "backend_echo"
    return "ecfs.scourt.go.kr/사건검색.md"


def test_ask_correction_becomes_lesson(tmp_path, monkeypatch):
    """풀루프: SOP 라우팅 런 → ask_human → 사람 교정 → propose_lesson → approve_lesson → 파일·커밋·재로딩."""
    repo, mem = setup_temp_repo(tmp_path, monkeypatch)
    sop_path = _teach_sop(monkeypatch)

    monkeypatch.setattr(main, "MODEL", _ask_then_done_model())
    monkeypatch.setattr(
        ma_mod, "MEMORY_MODEL", lesson_model([{"op": "ADD", "text": LESSON_TEXT, "target": None}])
    )

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "사건 조회해줘"})  # route()가 SOP로 라우팅
        ask = ws.receive_json()
        assert ask["type"] == "ask_human"
        ws.send_json({"type": "human_answer", "text": "끝자리가 5야"})  # 교정
        done_echo = ws.receive_json()
        assert done_echo["type"] == "backend_echo" and "조회 완료" in done_echo["text"]
        lesson = ws.receive_json()  # 런 종료 → 레슨 제안 카드
        assert lesson["type"] == "propose_lesson"
        assert lesson["path"] == sop_path
        assert LESSON_TEXT in lesson["diff"]
        ws.send_json({"type": "approve_lesson"})
        saved = ws.receive_json()
        assert saved["type"] == "backend_echo" and "레슨 반영됨" in saved["text"]

    # 파일 ## 레슨에 들어감 + 프론트매터/순서 보존
    content = (mem / "sop" / "ecfs.scourt.go.kr" / "사건검색.md").read_text(encoding="utf-8")
    assert LESSON_TEXT in content
    assert "## 레슨" in content and "## 순서" in content

    # 검증 기준: 다음 런에서 read_sop가 그 레슨을 로드(에이전트가 보고 안 물음)
    assert LESSON_TEXT in agent_mod.read_sop(sop_path)

    # 레슨 커밋은 SOP 파일만 건드림(인덱스 안 건드림)
    names = subprocess.run(
        ["git", "-c", "core.quotepath=false", "show", "--name-only", "--pretty=format:", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert names == ["memory/sop/ecfs.scourt.go.kr/사건검색.md"]


def test_oneoff_answer_no_lesson(tmp_path, monkeypatch):
    """일회성 답(배울 규칙 없음, ops=[]) → propose_lesson 카드가 안 뜬다."""
    setup_temp_repo(tmp_path, monkeypatch)
    _teach_sop(monkeypatch)
    monkeypatch.setattr(main, "MODEL", _ask_then_done_model())
    monkeypatch.setattr(ma_mod, "MEMORY_MODEL", lesson_model([]))  # 배울 것 없음

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "사건 조회해줘"})
        assert ws.receive_json()["type"] == "ask_human"
        ws.send_json({"type": "human_answer", "text": "이번 건은 2024가단99999"})
        assert "조회 완료" in ws.receive_json()["text"]
        # 레슨 카드가 없었음을 증명: 승인 시도 → 만료 안내(pending_lesson 없음)
        ws.send_json({"type": "approve_lesson"})
        warn = ws.receive_json()
    assert warn["type"] == "backend_echo" and "만료" in warn["text"]


def test_no_lesson_without_routed_sop(tmp_path, monkeypatch):
    """라우팅된 SOP가 없으면(자유 작업) 막혀 물어도 레슨을 만들지 않는다(붙일 대상 없음)."""
    setup_temp_repo(tmp_path, monkeypatch)  # 가르친 SOP 없음 → route() None
    monkeypatch.setattr(main, "MODEL", _ask_then_done_model())
    monkeypatch.setattr(
        ma_mod, "MEMORY_MODEL", lesson_model([{"op": "ADD", "text": LESSON_TEXT, "target": None}])
    )
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "아무 일이나 해줘"})
        assert ws.receive_json()["type"] == "ask_human"
        ws.send_json({"type": "human_answer", "text": "이렇게 해"})
        assert "조회 완료" in ws.receive_json()["text"]
        ws.send_json({"type": "approve_lesson"})
        warn = ws.receive_json()
    assert "만료" in warn["text"]  # 레슨 제안이 만들어지지 않음


def test_apply_lessons_reconciliation(tmp_path, monkeypatch):
    """화해 단위: ADD 추가 / EDIT 모순 교체(은퇴) / STRENGTHEN 가중치 +1 / EDIT target 없으면 ADD 폴백."""
    repo, mem = setup_temp_repo(tmp_path, monkeypatch)
    draft = SopDraft.model_validate(SOP_DICT)
    memory_store.approve("ecfs.scourt.go.kr", "사건검색", draft, ["법원은 본원만 선택"])
    sop_path = "ecfs.scourt.go.kr/사건검색.md"
    assert memory_store.read_lessons(sop_path) == ["법원은 본원만 선택"]

    # ADD
    memory_store.apply_lessons(sop_path, [LessonOp(op="ADD", text="사건번호 끝자리 완전일치")])
    assert set(memory_store.read_lessons(sop_path)) == {"법원은 본원만 선택", "사건번호 끝자리 완전일치"}

    # EDIT — 모순 레슨을 교체(은퇴, recency 우선)
    memory_store.apply_lessons(
        sop_path, [LessonOp(op="EDIT", text="법원이 지원이면 지원까지 선택", target="법원은 본원만 선택")]
    )
    lessons = memory_store.read_lessons(sop_path)
    assert "법원은 본원만 선택" not in lessons and "법원이 지원이면 지원까지 선택" in lessons

    # STRENGTHEN — 중복 없이 중요도 +1 → (×2) 렌더
    memory_store.apply_lessons(
        sop_path,
        [LessonOp(op="STRENGTHEN", text="법원이 지원이면 지원까지 선택", target="법원이 지원이면 지원까지 선택")],
    )
    content = (mem / "sop" / "ecfs.scourt.go.kr" / "사건검색.md").read_text(encoding="utf-8")
    assert "(×2) 법원이 지원이면 지원까지 선택" in content
    assert memory_store.read_lessons(sop_path).count("법원이 지원이면 지원까지 선택") == 1  # 중복 없음

    # EDIT target 못 찾으면 ADD 폴백
    n_before = len(memory_store.read_lessons(sop_path))
    memory_store.apply_lessons(sop_path, [LessonOp(op="EDIT", text="새 레슨", target="없는레슨")])
    after = memory_store.read_lessons(sop_path)
    assert "새 레슨" in after and len(after) == n_before + 1


def test_apply_lessons_preserves_human_tail(tmp_path, monkeypatch):
    """사람이 ## 레슨 뒤에 손으로 덧붙인 섹션은 레슨 재작성 시 보존된다(§9 직접 편집 허용)."""
    repo, mem = setup_temp_repo(tmp_path, monkeypatch)
    draft = SopDraft.model_validate(SOP_DICT)
    memory_store.approve("ecfs.scourt.go.kr", "사건검색", draft, ["기존 레슨"])
    sop_path = "ecfs.scourt.go.kr/사건검색.md"
    sop_file = mem / "sop" / "ecfs.scourt.go.kr" / "사건검색.md"
    # 사람이 레슨 섹션 아래에 메모를 덧붙임
    sop_file.write_text(
        sop_file.read_text(encoding="utf-8") + "\n## 사람 메모\n자유롭게 적은 내용\n",
        encoding="utf-8",
    )
    memory_store.apply_lessons(sop_path, [LessonOp(op="ADD", text="새 규칙")])
    content = sop_file.read_text(encoding="utf-8")
    assert "## 사람 메모" in content and "자유롭게 적은 내용" in content  # tail 보존
    assert "새 규칙" in content and "기존 레슨" in content  # 레슨도 반영
