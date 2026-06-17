"""FastAPI 앱 + /ws — 단일 에이전트 루프의 배관(§5).

수신 루프는 클라이언트 프레임만 읽어 라우팅한다. 추론은 agent.run()이 별도 asyncio 태스크에서
돌고, 관측은 obs_q로 도구에 배달된다. user_input이 런을 시작, observation이 큐를 채우고, stop이 취소한다.
"""

import asyncio
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic_ai import DeferredToolRequests, DeferredToolResults

import audit
import memory_store
import safety
import vault
from agent import MODEL, agent, render_observation
from memory_agent import distill, distill_lesson, verify_run
from session import CaptchaHandoff, RunHalted, Session, Stopped

app = FastAPI()


@app.get("/")
def health():
    return {"status": "ok"}


async def run_task(
    session: Session,
    task_text: str | None = None,
    message_history: list | None = None,
    deferred_results: DeferredToolResults | None = None,
) -> None:
    """agent.run() 한 번을 감싸 종료를 처리한다. done이면 결과를, 가드레일이면 사유를 보고하고,
    ask_human(DeferredToolRequests)이면 질문을 사이드패널로 푸시하고 사람 답을 기다린다(§6).

    message_history/deferred_results가 주어지면 사람 답을 받아 무상태로 재개하는 경로다."""
    try:
        result = await agent.run(
            task_text,
            deps=session,
            model=MODEL,
            message_history=message_history,
            deferred_tool_results=deferred_results,
        )
        if isinstance(result.output, DeferredToolRequests):
            out = result.output
            # 🔒 크리티컬 액션 승인 우선(§4·§11) — 제출 등 비가역 라벨은 성숙도/확신도 무관 사람 승인.
            if out.approvals:
                acall = out.approvals[0]
                idx = acall.args_as_dict().get("index")
                label = safety.label_for_index(session.last_observation, idx)
                session.pending_messages = result.all_messages()
                session.pending_approval_id = acall.tool_call_id
                audit.log("approval_requested", label=label, index=idx)
                await session.ws.send_json({"type": "approve_action", "label": label, "index": idx})
                return
            # 에이전트가 ask_human을 불렀다 → 질문을 푸시하고 재개에 필요한 상태를 보관.
            # 시스템 프롬프트가 "한 번에 도구 하나"를 강제하므로 calls는 ask_human 하나로 본다.
            call = out.calls[0]
            args = call.args_as_dict()
            session.pending_messages = result.all_messages()
            session.pending_call_id = call.tool_call_id
            session.last_question = args.get("question", "")  # 답과 짝지어 레슨 후보로(§7)
            await session.ws.send_json(
                {
                    "type": "ask_human",
                    "question": session.last_question,
                    "options": args.get("options"),
                }
            )
            return
        await session.ws.send_json({"type": "backend_echo", "text": f"완료: {result.output}"})
        usage = result.usage
        print(  # 캐시 동작 검증용 로깅(§12)
            f"[cache] read={getattr(usage, 'cache_read_tokens', None)} "
            f"write={getattr(usage, 'cache_write_tokens', None)}"
        )
        await maybe_verify_and_promote(session)  # done → 화면 증거로 성공 판정 → 졸업 집계(§10)
        await maybe_propose_lesson(session)  # 런 종료 → 이번에 물어본 것을 레슨으로(§7 경로②)
    except Stopped:
        pass  # STOP은 이미 클라이언트에 통지됨
    except CaptchaHandoff as e:
        # CAPTCHA는 외부 차단 — 사람 핸드오프만 알리고 SOP 성숙도엔 페널티 주지 않는다(§4).
        await session.ws.send_json({"type": "backend_echo", "text": f"핸드오프: {e.reason}"})
        audit.log("captcha_handoff", reason=e.reason)
    except RunHalted as e:
        await session.ws.send_json({"type": "backend_echo", "text": f"중단(가드레일): {e.reason}"})
        await maybe_verify_and_promote(session, success=False)  # 가드레일 중단 = 실패로 집계(§10)
        await maybe_propose_lesson(session)  # 막혀서 끝났어도 사람 답은 배울 가치가 있다
    except asyncio.CancelledError:
        raise  # STOP 취소 경로
    except Exception as e:  # 모델/네트워크 예외
        await session.ws.send_json({"type": "backend_echo", "text": f"오류: {e}"})


async def _reject_if_busy(session: Session, ws: WebSocket) -> bool:
    """진행 중인 작업이 있으면 안내하고 True. user_input·record_demo 공통 가드."""
    if session.task and not session.task.done():
        await ws.send_json({"type": "backend_echo", "text": "이미 작업이 진행 중입니다."})
        return True
    return False


def _site_from_events(events: list) -> str:
    """녹화된 행동의 url 호스트에서 사이트를 추론(없으면 scourt.go.kr). 사이트별 메모리 레이아웃에 사용."""
    for ev in events:
        url = ev.get("url") if isinstance(ev, dict) else None
        if url:
            try:
                host = urlparse(url).hostname or ""
            except ValueError:
                continue
            if host:
                return host
    return "scourt.go.kr"


async def run_distill(session: Session, site: str, name: str, events: list) -> None:
    """시연을 메모리 에이전트(Opus)로 증류해 SOP 제안을 푸시한다. 별도 태스크라 STOP으로 취소 가능,
    receive 루프는 증류 중에도 계속 응답한다(§7). 모델은 파일을 안 쓴다(§9)."""
    try:
        draft = await distill(events)
    except asyncio.CancelledError:
        raise  # STOP 취소
    except Exception as e:  # 증류 모델/네트워크 예외
        await session.ws.send_json({"type": "backend_echo", "text": f"증류 실패: {e}"})
        return
    session.pending_sop = {"site": site, "name": name, "draft": draft}
    await session.ws.send_json(
        {
            "type": "propose_sop",
            "path": f"sop/{site}/{name}.md",
            "diff": memory_store.render_sop(draft),
            "open_branches": draft.open_branches,
        }
    )


async def maybe_propose_lesson(session: Session) -> None:
    """런 종료 시, SOP 따라 일하다 물어본 Q&A를 레슨으로 증류해 승인 카드를 띄운다(§7 경로②).

    라우팅된 SOP가 없거나 물어본 게 없으면 아무것도 안 한다. 증류 실패는 보고만 하고 런 결과는 보존."""
    sop_path = session.active_sop_path
    candidates = session.lesson_candidates
    session.lesson_candidates = []  # 한 런의 후보는 한 번만 증류(재제안 방지)
    if not sop_path or not candidates:
        return
    try:
        existing = await asyncio.to_thread(memory_store.read_lessons, sop_path)
        goal = await asyncio.to_thread(memory_store.goal_for, sop_path)
        proposal = await distill_lesson(goal, existing, candidates)
    except asyncio.CancelledError:
        raise  # STOP 취소
    except Exception as e:  # 증류 모델/네트워크/파일 예외
        await session.ws.send_json({"type": "backend_echo", "text": f"레슨 증류 실패: {e}"})
        return
    if not proposal.ops:
        return  # 일회성 답 — 배울 레슨 없음
    session.pending_lesson = {"sop_path": sop_path, "ops": proposal.ops}
    await session.ws.send_json(
        {
            "type": "propose_lesson",
            "path": sop_path,
            "diff": memory_store.render_lesson_diff(sop_path, proposal.ops),
        }
    )


def _verify_passed(verify: dict, verdict) -> bool:
    """심판 판정을 졸업용 성공/실패로 환원하는 결정적 규칙(§9·§10).

    채워진 기준 종류가 ≥2이고 그 종류가 *전부* 통과해야 성공. 약한 verify(채워진 종류 <2)나
    한 종류라도 실패면 졸업 금지(§14-3 조용한 실패 방지). artifact는 MVP 미평가 → 채워졌으면 실패."""
    if verify.get("artifact"):
        return False  # 산출물 판정은 후순위 — 채워진 SOP는 졸업 보류
    filled = [k for k in ("must_appear", "must_match", "must_not") if verify.get(k)]
    if len(filled) < 2:
        return False
    return all(getattr(verdict, k) for k in filled)


async def maybe_verify_and_promote(session: Session, success: bool | None = None) -> None:
    """런 종료 시 SOP의 verify 기준을 최종 화면과 대조해 성공/실패를 졸업 카운터에 누적한다(§10).

    success=None이면 별도 심판 에이전트가 화면 증거로 판정(자기선언 금지). success=False면
    가드레일 중단 등 명백한 실패로 화면 판정 없이 집계. 라우팅된 SOP가 없으면 졸업 대상이 아니다."""
    sop_path = session.active_sop_path
    if not sop_path:
        return
    if success is None:
        verify = await asyncio.to_thread(memory_store.read_verify, sop_path)
        obs = session.last_observation
        if not verify or obs is None:
            return  # 기준/화면 없으면 약한 판정으로 졸업시키지 않고 집계 보류(§14-3)
        try:
            goal = await asyncio.to_thread(memory_store.goal_for, sop_path)
            verdict = await verify_run(goal, verify, session.task_text, render_observation(obs))
        except asyncio.CancelledError:
            raise  # STOP 취소
        except Exception as e:  # 심판 모델/네트워크 예외 — 보고만, 집계 보류(런 결과 보존)
            await session.ws.send_json({"type": "backend_echo", "text": f"성공 판정 실패: {e}"})
            return
        success = _verify_passed(verify, verdict)
    res = await asyncio.to_thread(memory_store.record_outcome, sop_path, success)
    audit.log("outcome", path=sop_path, success=success, level=res["level"])
    await session.ws.send_json(
        {
            "type": "maturity_update",
            "path": sop_path,
            "level": res["level"],
            "success_window": res["success_window"],
            "success": success,
            "promoted": res["promoted"],
            "demoted": res["demoted"],
        }
    )


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    session = Session(ws=websocket)
    try:
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")

            if mtype == "user_input":
                if await _reject_if_busy(session, websocket):
                    continue
                session.reset()
                text = msg.get("text", "")
                session.task_text = text  # 힌트 붙이기 전 원본 — verify 입력값 대조용(§10)
                # 배운 SOP가 있으면 결정적 라우팅으로 read_sop 힌트를 앞에 붙인다(§9). 모델이 최종 판단.
                sop_path = memory_store.route(text)
                if sop_path:
                    session.active_sop_path = sop_path  # 막혀 물으면 이 SOP에 레슨을 쌓는다(§7)
                    text = f"[힌트] read_sop('{sop_path}')로 이 업무의 SOP를 먼저 읽고 그 절차를 따르라.\n{text}"
                session.task = asyncio.create_task(run_task(session, text))

            elif mtype == "observation":
                await session.obs_q.put(msg.get("observation") or {})

            elif mtype == "human_answer":
                # ask_human 답을 받아 무상태로 재개한다(§6). 대기 중이 아니면 무시.
                if not session.pending_messages or session.pending_call_id is None:
                    continue
                call_id = session.pending_call_id
                answer = msg.get("text", "")
                audit.log("ask_human", question=session.last_question, answer=answer)
                # SOP 따라 일하다 막혀 물은 거라면, 질문+답을 런 종료 시 레슨으로 증류할 후보로 적재(§7).
                if session.active_sop_path and session.last_question is not None:
                    session.lesson_candidates.append(
                        {"question": session.last_question, "answer": answer}
                    )
                session.last_question = None
                results = DeferredToolResults()
                results.calls[call_id] = answer
                history = session.pending_messages
                session.clear_pending()
                session.resume()
                session.task = asyncio.create_task(
                    run_task(session, message_history=history, deferred_results=results)
                )

            elif mtype == "action_approval":
                # 🔒 크리티컬 액션 승인/거부를 받아 무상태로 재개한다(§4·§11). 대기 중이 아니면 무시.
                if not session.pending_messages or not session.pending_approval_id:
                    continue
                approval_id = session.pending_approval_id
                approved = bool(msg.get("approved"))
                audit.log("approval", approved=approved)
                results = DeferredToolResults()
                results.approvals[approval_id] = approved
                history = session.pending_messages
                session.clear_pending()
                session.resume()
                session.task = asyncio.create_task(
                    run_task(session, message_history=history, deferred_results=results)
                )

            elif mtype == "dismiss_question":
                # 사람이 이 질문을 닫고 다른 일을 시키려 한다 → 대기 상태만 비운다.
                # (런은 ask_human에서 이미 종료됐으므로 취소할 태스크는 없다.)
                session.clear_pending()

            elif mtype == "record_demo":
                # "가르치기" 시연이 들어왔다 → 메모리 에이전트(Opus)가 SOP 초안으로 증류 →
                # diff를 사이드패널에 띄워 사람 승인을 기다린다(§7 경로①). 모델은 파일을 안 쓴다(§9).
                if await _reject_if_busy(session, websocket):
                    continue
                events = msg.get("events") or []
                name = (msg.get("task") or "").strip()
                # 업무 이름은 파일명이 되므로 경로 구분자/탈출 차단(저장 가드와 대칭).
                if not name or not events or "/" in name or "\\" in name or ".." in name:
                    await websocket.send_json(
                        {"type": "backend_echo", "text": "녹화가 비어 있거나 이름이 올바르지 않아요."}
                    )
                    continue
                site = _site_from_events(events)
                # 증류는 수초 걸리는 Opus 호출 → 별도 태스크로 돌려 receive 루프·STOP 응답성 유지.
                session.task = asyncio.create_task(run_distill(session, site, name, events))

            elif mtype == "approve_sop":
                # 사람 원클릭 승인 = "배웠다" 순간 + 인젝션 잠금(§7). harness가 파일+인덱스를 원자적 커밋.
                if not session.pending_sop:
                    # 카드가 만료됨(새 작업·재연결로 제안이 사라짐) → 사용자에게 알린다(조용한 유실 방지).
                    await websocket.send_json(
                        {"type": "backend_echo", "text": "승인할 제안이 없어요(만료됨). 다시 가르쳐 주세요."}
                    )
                    continue
                p = session.pending_sop
                try:
                    # 파일 I/O + git을 스레드로 빼 이벤트 루프를 막지 않는다.
                    res = await asyncio.to_thread(
                        memory_store.approve, p["site"], p["name"], p["draft"], msg.get("branch_notes")
                    )
                except Exception as e:  # 파일/git 예외 — 제안을 남겨 재시도 가능하게.
                    await websocket.send_json({"type": "backend_echo", "text": f"저장 실패: {e}"})
                    continue
                session.pending_sop = None  # 성공했을 때만 비운다(실패 시 드래프트 보존)
                await websocket.send_json(
                    {"type": "backend_echo", "text": f"배웠어요 — SOP 저장됨: {res['file']}"}
                )

            elif mtype == "reject_sop":
                # 반려 → 제안 폐기(저장 안 함).
                session.pending_sop = None

            elif mtype == "approve_lesson":
                # 사람 원클릭 승인 = 레슨이 진짜 규칙이 되는 순간 + 인젝션 잠금(§7). harness가 화해 병합·커밋.
                if not session.pending_lesson:
                    await websocket.send_json(
                        {"type": "backend_echo", "text": "승인할 레슨 제안이 없어요(만료됨)."}
                    )
                    continue
                p = session.pending_lesson
                try:
                    res = await asyncio.to_thread(
                        memory_store.apply_lessons, p["sop_path"], p["ops"]
                    )
                except Exception as e:  # 파일/git 예외 — 제안을 남겨 재시도 가능하게.
                    await websocket.send_json({"type": "backend_echo", "text": f"레슨 저장 실패: {e}"})
                    continue
                session.pending_lesson = None  # 성공했을 때만 비운다
                await websocket.send_json(
                    {"type": "backend_echo", "text": f"배웠어요 — 레슨 반영됨: {res['file']}"}
                )

            elif mtype == "reject_lesson":
                # 반려 → 레슨 제안 폐기(저장 안 함).
                session.pending_lesson = None

            elif mtype == "register_credential":
                # 🔐 사이드패널 '자격증명' 카드 → 금고에 암호화 저장(§11). 값은 로컬 WS로 백엔드까지만
                # 가고 모델·관측·로그·UI엔 안 남는다(여기서 종류만 감사 로그에 남김).
                kind = msg.get("kind")
                value = msg.get("value") or ""
                try:
                    await asyncio.to_thread(vault.put, kind, value)
                except ValueError as e:
                    await websocket.send_json({"type": "backend_echo", "text": f"자격증명 등록 실패: {e}"})
                    continue
                audit.log("credential_registered", kind=kind)  # 종류만 — 값은 절대 기록 안 함
                await websocket.send_json({"type": "backend_echo", "text": f"자격증명 등록됨: {kind}"})

            elif mtype == "stop":
                session.stopped = True
                session.pending_sop = None
                session.pending_lesson = None
                session.clear_pending()
                if session.task and not session.task.done():
                    session.task.cancel()
                await websocket.send_json({"type": "stopped"})
    except WebSocketDisconnect:
        if session.task and not session.task.done():
            session.task.cancel()
