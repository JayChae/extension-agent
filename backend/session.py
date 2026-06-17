"""연결당 세션 — WebSocket 위에서 에이전트 도구가 관측을 주고받는 RPC 다리.

수신 루프(main.py)만이 ws의 유일한 reader다. 읽은 관측은 `obs_q`에 넣고,
도구는 `act()`에서 `obs_q.get()`으로만 받는다 → 단일 양방향 채널을 한 reader로 안전하게 공유.
가드레일 4종(스텝 예산·무진전·연속 실패·전역 타임아웃)을 act() 둘레에서 코드로 강제한다(§6).
"""

import asyncio
import hashlib
import time
from collections import deque
from dataclasses import dataclass, field

from fastapi import WebSocket

# 가드레일 상수 (§6)
HAPPY_PATH_STEPS = 8
DEFAULT_STEP_BUDGET = HAPPY_PATH_STEPS * 3  # 행복경로 × 3 = 24
NO_PROGRESS_WINDOW = 6  # 최근 관측 해시를 몇 개까지 보나
NO_PROGRESS_REPEAT = 3  # 같은 화면 해시가 윈도우 안에서 이만큼 반복되면 무진전
MAX_CONSEC_FAILS = 3  # 연속 실패 K회
WALL_CLOCK_TIMEOUT = 180.0  # 초, 전역


class RunHalted(Exception):
    """가드레일이 런을 중단시킬 때. run_task 래퍼가 잡아 사용자에게 보고한다."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class Stopped(RunHalted):
    """사용자 STOP 전용 — 이미 클라이언트에 통지됐으므로 추가 보고 안 함."""


def _tool_sig(action: dict) -> str | None:
    """같은 도구+대상 연속 반복(무진전) 감지용 시그니처.
    화면을 안 바꾸고 읽기만 하는 perceive/extract/read는 None(반복 정상)."""
    kind = action.get("kind")
    if kind in ("click", "type", "select"):
        return f"{kind}:{action.get('index')}"
    if kind == "navigate":
        return f"navigate:{action.get('url')}"
    if kind == "scroll":
        return f"scroll:{action.get('dir')}"
    return None


def _obs_hash(obs: dict) -> str:
    """page-state(url+title+요소+표)만 해싱 — note/타임스탬프 등 변동 잡음 제외."""
    page = obs.get("page") or {}
    payload = "\n".join(
        [
            page.get("url", ""),
            page.get("title", ""),
            "\n".join(obs.get("elements") or []),
            "\n".join(obs.get("tables") or []),
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class Session:
    ws: WebSocket
    obs_q: asyncio.Queue = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None
    stopped: bool = False
    steps: int = 0
    fails: int = 0
    started_at: float = 0.0
    budget: int = DEFAULT_STEP_BUDGET
    recent_hashes: deque = field(default_factory=lambda: deque(maxlen=NO_PROGRESS_WINDOW))
    last_tool_sig: str | None = None
    pending_messages: list | None = None  # ask_human 대기 중 보관하는 message_history(§6)
    pending_call_id: str | None = None  # 재개 시 답을 매칭할 ask_human tool_call_id
    pending_sop: dict | None = None  # 승인 대기 중인 SOP 제안 {site, name, draft}(§7 학습)
    active_sop_path: str | None = None  # 이번 런이 라우팅된 SOP(레슨을 붙일 대상)(§7 경로②)
    last_question: str | None = None  # 직전 ask_human 질문(답과 짝지어 레슨 후보로)
    lesson_candidates: list = field(default_factory=list)  # [{question, answer}, ...] 런 종료 시 증류
    pending_lesson: dict | None = None  # 승인 대기 중인 레슨 제안 {sop_path, ops}(§7 화해)
    task_text: str | None = None  # 이번 런의 원본 요청(verify 입력값 대조용)(§10 Phase 8)
    last_observation: dict | None = None  # 마지막 성공 관측 = 최종 화면(verify 판정 대상)(§10)

    def reset(self) -> None:
        """새 작업 시작 직전 카운터 초기화 + 잔여 관측 비우기."""
        self.stopped = False
        self.steps = 0
        self.fails = 0
        self.budget = DEFAULT_STEP_BUDGET  # 런 시작마다 현재 상수에서 다시 읽음(테스트·향후 task별 조정 가능)
        self.started_at = time.monotonic()
        self.recent_hashes.clear()
        self.last_tool_sig = None
        self.pending_sop = None
        self.active_sop_path = None
        self.last_question = None
        self.lesson_candidates = []
        self.pending_lesson = None
        self.task_text = None
        self.last_observation = None
        self.clear_pending()
        while not self.obs_q.empty():
            self.obs_q.get_nowait()

    def clear_pending(self) -> None:
        """ask_human 대기 상태를 비운다. 두 필드는 항상 함께 세팅·해제된다(재개·닫기·STOP·reset 공통)."""
        self.pending_messages = None
        self.pending_call_id = None

    def resume(self) -> None:
        """ask_human 답을 받아 재개하기 직전. wall-clock만 다시 잡고(사람이 생각한 시간은
        타임아웃에 안 셈) steps/fails/관측해시는 보존해 전체 작업량 제한은 유지한다(§6).
        단 last_tool_sig는 비운다 — 사람 답은 정당한 상태 변화라, 답 직후 같은 동작이 와도
        '같은 동작 반복' 무진전 가드에 걸리면 안 된다(ask_human이 풀어준 분기를 다시 막는 꼴)."""
        self.started_at = time.monotonic()
        self.last_tool_sig = None

    def _guard_before(self, action: dict) -> None:
        if self.stopped:
            raise Stopped("STOP")
        if self.steps >= self.budget:
            raise RunHalted("스텝 예산 초과")
        if time.monotonic() - self.started_at > WALL_CLOCK_TIMEOUT:
            raise RunHalted("전역 타임아웃")
        sig = _tool_sig(action)
        if sig is not None and sig == self.last_tool_sig:
            raise RunHalted("무진전: 같은 동작 반복")
        self.last_tool_sig = sig

    def _guard_after(self, obs: dict) -> None:
        if not obs.get("ok"):
            self.fails += 1
            if self.fails >= MAX_CONSEC_FAILS:
                raise RunHalted("연속 실패")
            return  # 실패 관측은 무진전 해시 집계에서 제외
        self.fails = 0
        h = _obs_hash(obs)
        self.recent_hashes.append(h)
        if self.recent_hashes.count(h) >= NO_PROGRESS_REPEAT:
            raise RunHalted("무진전: 화면 변화 없음")

    async def act(self, action: dict) -> dict:
        """command 전송 → 매칭 observation 1개 수신(1 command ⇒ 1 observation 계약)."""
        self._guard_before(action)
        await self.ws.send_json({"type": "command", "action": action})
        obs = await self.obs_q.get()
        self.steps += 1
        self._guard_after(obs)
        # 최종 화면 = 마지막 관측(성공/실패 무관). 마지막 액션이 실패로 끝나면 verify가 그 실패 화면을
        # 봐야 한다 — 옛 성공 화면을 보면 실패한 런을 성공으로 졸업시킨다(§14-3 조용한 실패 방지)(§10).
        self.last_observation = obs
        return obs
