"""FastAPI 앱 + /ws — 단일 에이전트 루프의 배관(§5).

수신 루프는 클라이언트 프레임만 읽어 라우팅한다. 추론은 agent.run()이 별도 asyncio 태스크에서
돌고, 관측은 obs_q로 도구에 배달된다. user_input이 런을 시작, observation이 큐를 채우고, stop이 취소한다.
"""

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic_ai import DeferredToolRequests, DeferredToolResults

from agent import MODEL, agent
from session import RunHalted, Session, Stopped

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
            # 에이전트가 ask_human을 불렀다 → 질문을 푸시하고 재개에 필요한 상태를 보관.
            # 시스템 프롬프트가 "한 번에 도구 하나"를 강제하므로 calls는 ask_human 하나로 본다.
            call = result.output.calls[0]
            args = call.args_as_dict()
            session.pending_messages = result.all_messages()
            session.pending_call_id = call.tool_call_id
            await session.ws.send_json(
                {
                    "type": "ask_human",
                    "question": args.get("question", ""),
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
    except Stopped:
        pass  # STOP은 이미 클라이언트에 통지됨
    except RunHalted as e:
        await session.ws.send_json({"type": "backend_echo", "text": f"중단(가드레일): {e.reason}"})
    except asyncio.CancelledError:
        raise  # STOP 취소 경로
    except Exception as e:  # 모델/네트워크 예외
        await session.ws.send_json({"type": "backend_echo", "text": f"오류: {e}"})


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    session = Session(ws=websocket)
    try:
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")

            if mtype == "user_input":
                if session.task and not session.task.done():
                    await websocket.send_json(
                        {"type": "backend_echo", "text": "이미 작업이 진행 중입니다."}
                    )
                    continue
                session.reset()
                session.task = asyncio.create_task(run_task(session, msg.get("text", "")))

            elif mtype == "observation":
                await session.obs_q.put(msg.get("observation") or {})

            elif mtype == "human_answer":
                # ask_human 답을 받아 무상태로 재개한다(§6). 대기 중이 아니면 무시.
                if not session.pending_messages:
                    continue
                results = DeferredToolResults()
                results.calls[session.pending_call_id] = msg.get("text", "")
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

            elif mtype == "stop":
                session.stopped = True
                session.clear_pending()
                if session.task and not session.task.done():
                    session.task.cancel()
                await websocket.send_json({"type": "stopped"})
    except WebSocketDisconnect:
        if session.task and not session.task.done():
            session.task.cancel()
