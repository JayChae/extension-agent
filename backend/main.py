from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()


@app.get("/")
def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    """사이드패널 ↔ 백엔드 양방향 채널. Phase 2는 echo만 — 추론 없음."""
    await websocket.accept()
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "user_input":
                await websocket.send_json(
                    {"type": "backend_echo", "text": f"[backend] {msg.get('text', '')}"}
                )
            elif msg.get("type") == "stop":
                await websocket.send_json({"type": "stopped"})
    except WebSocketDisconnect:
        pass
