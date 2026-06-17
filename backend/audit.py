"""평문 감사 로그 — append-only JSONL(§11·§13). 해시체인/WORM은 v2.

관측·제안 액션·인간 승인·실행 결과를 한 줄 JSON으로 남긴다. 비밀값은 애초에 흘러오지 않지만
(관측에 input value 없음 §3, 비밀 입력은 금고 경로 — 다음 단계) 본문 대신 요약만 남겨 보수적으로 둔다.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

# 운영 로그라 git 미추적(.gitignore: backend/audit/). 테스트는 LOG_PATH를 임시 경로로 덮어쓴다.
LOG_PATH = Path(
    os.getenv("AUDIT_LOG") or (Path(__file__).resolve().parent / "audit" / "audit.jsonl")
)


def log(event: str, **fields) -> None:
    """{ts, time, event, ...fields} 한 줄을 LOG_PATH에 append한다. 실패해도 런을 막지 않는다."""
    rec = {"ts": time.time(), "time": datetime.now(timezone.utc).isoformat(), "event": event}
    rec.update(fields)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 감사 로그 쓰기 실패가 작업을 멈추게 하면 안 된다(베스트에포트).
