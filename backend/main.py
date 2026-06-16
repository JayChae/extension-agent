from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()

USAGE = (
    "명령: perceive | click N | type N <텍스트> | select N <옵션> | "
    "navigate <url> | scroll up|down | extract <질의>"
)


def parse_command(text: str) -> dict | None:
    """채팅 한 줄을 구조화 액션으로 파싱.

    Phase 3 임시 스캐폴딩 — Phase 4에서 Pydantic AI agent.run()이 이 자리를 대체한다.
    무효 입력이면 None.
    """
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return None
    cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if cmd == "perceive":
        return {"kind": "perceive"}
    if cmd == "navigate" and rest:
        return {"kind": "navigate", "url": rest}
    if cmd == "scroll":
        return {"kind": "scroll", "dir": "up" if rest.strip() == "up" else "down"}
    if cmd == "extract":
        return {"kind": "extract", "query": rest}

    # 인덱스를 받는 명령: click / type / select
    if cmd in ("click", "type", "select"):
        idx_str, _, arg = rest.partition(" ")
        if not idx_str.isdigit():
            return None
        index = int(idx_str)
        if cmd == "click":
            return {"kind": "click", "index": index}
        if cmd == "type":
            return {"kind": "type", "index": index, "text": arg}
        if cmd == "select":
            return {"kind": "select", "index": index, "option": arg}
    return None


def format_observation(obs: dict) -> str:
    """content 관측을 받았다는 짧은 확인(왕복 증명용).

    전체 요소 목록은 사이드패널이 이미 화면에 보여주므로, 백엔드 회신은 중복 덤프 없이
    개수만 요약한다.
    """
    if not obs or not obs.get("ok"):
        return "✖ " + str((obs or {}).get("error") or (obs or {}).get("note") or "실패")
    n_el = len(obs.get("elements") or [])
    n_tb = len(obs.get("tables") or [])
    head = f"✓ 백엔드 수신: 요소 {n_el}개, 표 {n_tb}개"
    note = obs.get("note")
    return f"{head} · {note}" if note else head


@app.get("/")
def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    """사이드패널 ↔ 백엔드 양방향 채널.

    Phase 3: 채팅 명령을 파싱해 구조화 액션을 내려보내고(command),
    content가 실행 후 돌려준 관측(observation)을 포맷해 회신한다(observation_ack).
    추론 루프는 없음 — Phase 4에서 agent.run()이 들어온다.
    """
    await websocket.accept()
    try:
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")
            if mtype == "user_input":
                action = parse_command(msg.get("text", ""))
                if action is None:
                    await websocket.send_json({"type": "backend_echo", "text": USAGE})
                else:
                    await websocket.send_json({"type": "command", "action": action})
            elif mtype == "observation":
                text = format_observation(msg.get("observation") or {})
                await websocket.send_json({"type": "observation_ack", "text": text})
            elif mtype == "stop":
                await websocket.send_json({"type": "stopped"})
    except WebSocketDisconnect:
        pass
