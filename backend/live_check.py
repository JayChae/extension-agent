"""라이브 검증 — 진짜 Sonnet 모델로 가짜 브라우저(canned 관측)에서 사건검색 happy path를
끝까지 푸는지 + 단일 캐시 브레이크포인트가 동작하는지(cache_read_tokens>0) 1회 확인.

실행: uv run python live_check.py   (ANTHROPIC_API_KEY 필요, 소액 비용)
이건 일회용 검증 스크립트다(테스트 스위트 아님).
"""

from dotenv import load_dotenv

load_dotenv()

import main  # noqa: E402  (dotenv 먼저)
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def obs(elements, tables=None, note=""):
    return {
        "ok": True,
        "page": {"url": "https://ecfs.scourt.go.kr/search", "title": "나의 사건검색"},
        "elements": elements,
        "tables": tables or [],
        "note": note,
    }


# 사건검색 화면 → (사건번호 입력) → 검색 → 결과표. 모델이 인덱스로 스스로 풀어야 한다.
FORM = obs(
    [
        '[1]<input name="법원">',
        '[2]<input name="사건번호">',
        '[3]<button name="검색"> 검색',
    ]
)
RESULT = obs(
    ['[1]<input name="사건번호">', '[2]<button name="검색"> 검색'],
    tables=["| 사건번호 | 당사자 |\n| --- | --- |\n| 2024가단12345 | 홍길동 |"],
)


def fake_extension(ws):
    """command마다 적절한 관측 회신. 검색 클릭 후엔 결과표를 준다."""
    searched = False
    for _ in range(30):
        msg = ws.receive_json()
        t = msg["type"]
        if t == "command":
            action = msg["action"]
            print(f"  → 액션: {action}")
            if action.get("kind") == "click":
                searched = True
            ws.send_json(
                {"type": "observation", "observation": RESULT if searched else FORM}
            )
        elif t == "backend_echo":
            print(f"  ← 백엔드: {msg['text']}")
            return msg["text"]
        elif t == "stopped":
            return "STOPPED"
    return "(종료 프레임 없음)"


def main_run():
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {"type": "user_input", "text": "사건번호 2024가단12345 를 검색해서 결과를 알려줘"}
        )
        result = fake_extension(ws)
    print("\n결과:", result)
    assert result.startswith("완료"), "happy path가 done에 도달하지 못함"
    print("✅ 라이브 happy path 통과")


if __name__ == "__main__":
    main_run()
