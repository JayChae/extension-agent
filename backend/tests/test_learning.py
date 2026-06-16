"""Phase 6 자동 검증 — "가르치면 기억한다"(Show me → SOP) 학습 루프를
가짜 메모리 에이전트(FunctionModel) + 임시 git repo + TestClient WS로 결정적·무비용 검증한다.

검증(§13 Phase 6): 시연(record_demo) → 증류·제안(propose_sop) → 승인(approve_sop) → git 커밋 →
다음 런에서 route()가 그 SOP로 라우팅하고 read_sop가 그 절차를 불러온다.
"""

import subprocess

import agent as agent_mod
import main
import memory_agent as ma_mod
import memory_store
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

client = TestClient(main.app)

SOP_DICT = {
    "goal": "사건번호로 사건 진행 상태를 조회한다",
    "input_slots": [{"name": "사건번호", "desc": "예: 2024가단12345"}],
    "verify": {
        "must_appear": ["접수번호 텍스트가 결과영역에 존재"],
        "must_match": ["결과 행 사건번호 == {사건번호} (끝자리까지 완전일치)"],
        "must_not": ["'오류' 텍스트"],
        "artifact": [],
    },
    "steps": ["사건번호 칸에 {사건번호} 입력", "검색 버튼 클릭"],
    "open_branches": ["결과 0건이면?", "여러 건이면?"],
}


def distiller_model():
    """메모리 에이전트(증류) 대역 — output 도구 final_result로 SopDraft를 낸다(공식 기본 이름)."""

    def fn(messages, info):
        return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=SOP_DICT)])

    return FunctionModel(fn)


def setup_temp_repo(tmp_path, monkeypatch):
    """임시 git repo + memory 디렉토리로 REPO_ROOT/MEMORY_DIR를 갈아끼운다(읽기 경로도 일치)."""
    repo = tmp_path
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "tester"], cwd=repo, check=True)
    mem = repo / "memory"
    mem.mkdir()
    monkeypatch.setattr(memory_store, "REPO_ROOT", repo)
    monkeypatch.setattr(memory_store, "MEMORY_DIR", mem)
    monkeypatch.setattr(agent_mod, "MEMORY_DIR", mem)  # read_sop가 같은 위치를 읽도록
    return repo, mem


def test_teach_distill_approve_commit_reload(tmp_path, monkeypatch):
    repo, mem = setup_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(ma_mod, "MEMORY_MODEL", distiller_model())

    events = [
        {"kind": "action", "action": "click", "role": "link", "name": "나의 사건검색", "cue": "상단 메뉴"},
        {"kind": "note", "text": "사건번호는 끝자리까지 정확히"},
        {"kind": "action", "action": "type", "role": "textbox", "name": "사건번호", "value": "2024가단12345"},
        {"kind": "action", "action": "click", "role": "button", "name": "검색"},
    ]

    with client.websocket_connect("/ws") as ws:
        # 1) 시연 전송 → 증류·제안
        ws.send_json({"type": "record_demo", "task": "사건검색", "events": events})
        proposal = ws.receive_json()
        assert proposal["type"] == "propose_sop"
        assert proposal["path"] == "sop/scourt.go.kr/사건검색.md"
        assert "{사건번호}" in proposal["diff"]  # 파라미터화됨
        assert proposal["open_branches"]  # 미해결 분기 명시

        # 2) 승인(+분기 설명을 레슨으로) → 저장·커밋
        ws.send_json(
            {"type": "approve_sop", "branch_notes": ["결과 0건이면? → 다시 검색"]}
        )
        echo = ws.receive_json()
        assert echo["type"] == "backend_echo"
        assert "SOP 저장됨" in echo["text"]

    # 3) 파일 + 인덱스가 기록됨
    sop_file = mem / "sop" / "scourt.go.kr" / "사건검색.md"
    content = sop_file.read_text(encoding="utf-8")
    assert "{사건번호}" in content
    assert "LEARNING" in content  # harness가 찍은 성숙도
    assert "결과 0건이면? → 다시 검색" in content  # 분기 설명이 레슨으로
    index = (mem / "master_index.json").read_text(encoding="utf-8")
    assert "사건검색" in index

    # 4) 단일 git 커밋이 그 두 경로만 건드림
    names = subprocess.run(
        ["git", "-c", "core.quotepath=false", "show", "--name-only", "--pretty=format:", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert sorted(names) == sorted(
        ["memory/master_index.json", "memory/sop/scourt.go.kr/사건검색.md"]
    )

    # 5) 라우팅: 다른 표현도 그 SOP로, 무관한 입력은 None
    assert memory_store.route("사건 조회해줘") == "scourt.go.kr/사건검색.md"
    assert memory_store.route("날씨 알려줘") is None

    # 6) read_sop가 저장된 절차를 그대로 불러온다(다음 런 로딩)
    assert agent_mod.read_sop("scourt.go.kr/사건검색.md") == content


def test_reload_run_injects_sop_hint(tmp_path, monkeypatch):
    """다음 런: user_input이 라우팅 힌트로 read_sop 경로를 모델에 주입하고, 모델이 그걸 읽고 done."""
    repo, mem = setup_temp_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(ma_mod, "MEMORY_MODEL", distiller_model())

    # 먼저 한 번 가르쳐 둔다
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "type": "record_demo",
                "task": "사건검색",
                "events": [{"kind": "action", "action": "click", "role": "button", "name": "검색"}],
            }
        )
        assert ws.receive_json()["type"] == "propose_sop"
        ws.send_json({"type": "approve_sop"})
        assert ws.receive_json()["type"] == "backend_echo"

    # 스텝 모델: 첫 프롬프트(힌트 포함)를 잡아두고 read_sop → done
    captured = []
    steps = [("read_sop", {"path": "scourt.go.kr/사건검색.md"}), ("done", {"result": "조회 완료"})]
    state = {"i": 0}

    def step_fn(messages, info):
        if not captured:
            for m in messages:
                for p in getattr(m, "parts", []):
                    if p.__class__.__name__ == "UserPromptPart":
                        captured.append(str(p.content))
        i = state["i"]
        state["i"] += 1
        name, args = steps[i]
        return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args)])

    monkeypatch.setattr(main, "MODEL", FunctionModel(step_fn))

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "사건 조회해줘"})
        echo = ws.receive_json()  # read_sop는 WS를 안 거치므로 바로 종료 echo
    assert echo["type"] == "backend_echo"
    assert "조회 완료" in echo["text"]
    # 라우팅 힌트가 실제로 모델 입력에 주입됨
    assert captured and "read_sop('scourt.go.kr/사건검색.md')" in captured[0]


def test_approve_without_pending_warns():
    """만료된 카드 승인 → 조용히 무시하지 말고 만료를 알린다(조용한 유실 방지)."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "approve_sop"})
        echo = ws.receive_json()
    assert echo["type"] == "backend_echo"
    assert "만료" in echo["text"]


def test_invalid_task_name_rejected(monkeypatch):
    """경로 구분자/탈출이 든 업무 이름은 증류 전에 거부(파일명 안전)."""
    monkeypatch.setattr(ma_mod, "MEMORY_MODEL", distiller_model())
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "type": "record_demo",
                "task": "../evil",
                "events": [{"kind": "action", "action": "click", "role": "button", "name": "x"}],
            }
        )
        echo = ws.receive_json()
    assert echo["type"] == "backend_echo"
    assert "올바르지" in echo["text"]


def test_site_derived_from_recorded_url(tmp_path, monkeypatch):
    """사이트는 녹화된 url 호스트에서 추론된다(하드코딩 아님 — 범용 확장 친화)."""
    setup_temp_repo(tmp_path, monkeypatch)
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
                        "url": "https://ecfs.scourt.go.kr/page",
                    }
                ],
            }
        )
        proposal = ws.receive_json()
    assert proposal["type"] == "propose_sop"
    assert proposal["path"] == "sop/ecfs.scourt.go.kr/사건검색.md"
