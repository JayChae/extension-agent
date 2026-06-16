"""메모리 전담 에이전트 — "어떻게 잘 기억할지"만 담당하는 강한 모델(Opus) (§7).

수행 에이전트(agent.py, Sonnet 스텝 루프)와 **분리된** 에이전트다. 이 파일이 앞으로 모든 메모리
쓰기 *제안*의 집이 된다. Phase 6 능력은 "시연→SOP 증류" 하나. Phase 7이 같은 에이전트/프롬프트
인프라에 교정→레슨·화해(ADD/EDIT/STRENGTHEN)를 더한다.

⚠️ 안전 불변식(§9): 이 에이전트는 파일을 직접 쓰지 않는다. 구조화된 제안(SopDraft)만 내고,
사람 승인 후 harness(memory_store.py)가 git에 기록한다(인젝션·불일치 방지).
"""

import os

from pydantic import BaseModel, Field
from pydantic_ai import Agent

# 증류 모델은 문서상 기본 Opus. 크레딧·비용 사정이면 MEMORY_MODEL/AGENT_MODEL로 교체(§12, agent.py와 같은 패턴).
MEMORY_MODEL = os.getenv("MEMORY_MODEL") or os.getenv("AGENT_MODEL") or "anthropic:claude-opus-4-8"

MEMORY_PROMPT = """\
너는 사람이 보여준 웹 업무 시연을 재사용 가능한 SOP(작업 절차서)로 증류하는 메모리 작성가다.
입력은 한 번의 시연 기록이다 — 사람이 직접 한 *행동*들과, 중간중간 적어준 *설명*이 시간순으로 엮여 있다.

[증류 원칙]
- 특정값(사건번호 "2024가단12345", 법원명 등)은 `{슬롯}`으로 일반화하고 input_slots에 등록한다.
  단 버튼/메뉴의 고정 라벨("검색", "나의 사건검색")은 그대로 둔다.
- steps는 셀렉터나 XPath가 아니라 자연어로 적는다(런타임에 다시 그라운딩되도록). 요소는 역할+이름+텍스트로.
- 사람이 설명으로 알려준 조건/주의는 절차에 녹이거나 레슨처럼 step에 명시한다.
- 한 번의 시연은 행복경로 골격일 뿐이다. 사람이 설명하지 않은 미해결 분기(예: 결과 0건/여러 건,
  지원 vs 본원)는 추측하지 말고 open_branches에 질문 형태로 남긴다.
- verify는 결정적 성공 판정이다. 자유서술 금지, 가능한 신호만(must_appear/must_match/must_not/artifact).
  예: 사건검색은 "결과 행 사건번호 == {사건번호} (끝자리까지 완전일치)"를 must_match로.
"""


class InputSlot(BaseModel):
    """SOP를 재사용할 때 채워 넣는 빈칸."""

    name: str = Field(description="슬롯 이름, 예: 사건번호")
    desc: str = Field(description="설명/예시, 예: 예: 2024가단12345")


class Verify(BaseModel):
    """결정적 성공 판정(§9·§10). 4종 중 ≥2종을 채운다."""

    must_appear: list[str] = Field(default_factory=list, description="결과에 나타나야 하는 긍정 신호")
    must_match: list[str] = Field(default_factory=list, description="입력-출력 일치 조건")
    must_not: list[str] = Field(default_factory=list, description="없어야 하는 부정 신호(오류 등)")
    artifact: list[str] = Field(default_factory=list, description="(해당 시) 산출물 존재 조건")


class SopDraft(BaseModel):
    """시연에서 증류된 SOP 초안. 메모리 에이전트의 구조화 출력."""

    goal: str = Field(description="이 업무가 달성하는 것 한 줄")
    input_slots: list[InputSlot] = Field(default_factory=list)
    verify: Verify
    steps: list[str] = Field(description="자연어 절차(셀렉터 금지)")
    open_branches: list[str] = Field(
        default_factory=list, description="시연이 못 담은 미해결 분기(다음에 그 상황을 만나면 ask_human)"
    )


memory_agent = Agent(output_type=SopDraft, instructions=MEMORY_PROMPT)


def _render_trace(events: list[dict]) -> str:
    """행동 record와 사람 설명(note)을 시간순 한 trace 문자열로 엮는다(모델 입력)."""
    lines = []
    n = 0
    for ev in events:
        kind = ev.get("kind")
        if kind == "note":
            text = ev.get("text", "")
            if text:
                lines.append(f"[설명] {text}")
            continue
        if kind != "action":
            continue  # 알 수 없는 이벤트는 무시(행동으로 오해해 가짜 스텝 만들지 않게)
        n += 1
        role = ev.get("role") or ev.get("action") or "?"
        name = ev.get("name") or ev.get("text") or ""
        part = f"{n}. {ev.get('action', '?')}: <{role}> {name}".rstrip()
        cue = ev.get("cue")
        if cue:
            part += f"  (주변: {cue})"
        value = ev.get("value")
        if value:
            part += f'  입력값="{value}"'
        url = ev.get("url")
        if url:
            part += f"  @ {url}"
        lines.append(part)
    return "\n".join(lines)


async def distill(events: list[dict]) -> SopDraft:
    """시연 기록(행동+설명)을 SopDraft로 증류한다. 모델은 런 시점에 주입(키 없이 import 가능)."""
    trace = _render_trace(events)
    result = await memory_agent.run(trace, model=MEMORY_MODEL)
    return result.output
