"""FastAPI 앱 + /ws — 단일 에이전트 루프의 배관(§5).

수신 루프는 클라이언트 프레임만 읽어 라우팅한다. 추론은 agent.run()이 별도 asyncio 태스크에서
돌고, 관측은 obs_q로 도구에 배달된다. user_input이 런을 시작, observation이 큐를 채우고, stop이 취소한다.
"""

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from agent import MODEL, agent
from session import RunHalted, Session, Stopped

app = FastAPI()


@app.get("/")
def health():
    return {"status": "ok"}


async def run_task(session: Session, task_text: str) -> None:
    """agent.run() 한 번을 감싸 종료를 처리한다. done이면 결과를, 가드레일이면 사유를 사용자에게 보고."""
    try:
        result = await agent.run(task_text, deps=session, model=MODEL)
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

            elif mtype == "stop":
                session.stopped = True
                if session.task and not session.task.done():
                    session.task.cancel()
                await websocket.send_json({"type": "stopped"})
    except WebSocketDisconnect:
        if session.task and not session.task.done():
            session.task.cancel()
