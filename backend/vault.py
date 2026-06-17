"""🔐 자격증명 금고 — 비밀값을 암호화해 보관·입력(§11). Claude는 값을 절대 못 본다.

로그인 ID·비번·공동인증서 PIN을 Fernet(대칭 암호화)로 디스크에 보관한다. 등록은 사이드패널
'자격증명' 카드에서 1회 — 값은 로컬 WS로 백엔드까지만 가고 모델·관측·로그·SOP 어디에도 안 남는다.
모델은 `fill_credential(index, kind)`로 *종류*만 지정하고, harness가 금고에서 꺼내 직접 입력한다.

마스터키는 env VAULT_KEY를 우선 쓰고, 없으면 backend/vault/master.key를 자동 생성·재사용한다(키·암호문
모두 git 미추적, 백엔드 전용). audit.py처럼 경로/키는 모듈 전역이라 테스트가 monkeypatch한다.
"""

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

# 마스터키(Fernet base64). env가 있으면 우선(배포 시 주입). 없으면 KEY_PATH에서 자동 생성·재사용.
VAULT_KEY = os.getenv("VAULT_KEY")
KEY_PATH = Path(__file__).resolve().parent / "vault" / "master.key"
# 암호문 저장 파일 — git 미추적(.gitignore: backend/vault/). 테스트는 SECRETS_PATH를 임시 경로로 덮어쓴다.
SECRETS_PATH = Path(__file__).resolve().parent / "vault" / "secrets.json"

# 허용 비밀 종류(고정). 그 외 kind는 거부 — 모델이 임의 키로 금고를 휘젓지 못하게.
KINDS = ("login_id", "login_pw", "cert_pin")


def _key() -> bytes | None:
    """마스터키 바이트. env VAULT_KEY 우선 → 없으면 KEY_PATH 자동 생성·재사용. 쓰기 실패 시 None(비활성)."""
    if VAULT_KEY:
        return VAULT_KEY.encode()
    try:
        if KEY_PATH.exists():
            return KEY_PATH.read_bytes()
        key = Fernet.generate_key()
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        # 배타 생성("x") — 동시 첫 호출 경합 시 먼저 쓴 키가 이기고, 진 쪽은 그 키를 읽는다.
        # (서로 다른 키를 덮어써 기존 암호문이 복호화 불능이 되는 사고 방지.)
        try:
            with KEY_PATH.open("xb") as fh:
                fh.write(key)
            return key
        except FileExistsError:
            return KEY_PATH.read_bytes()
    except OSError:
        return None


def _fernet() -> Fernet | None:
    """마스터키로 Fernet을 만든다. 키가 없거나 형식이 틀리면 None(금고 비활성)."""
    k = _key()
    if not k:
        return None
    try:
        return Fernet(k)
    except (ValueError, TypeError):
        return None


def _load() -> dict:
    try:
        return json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def put(kind: str, value: str) -> None:
    """비밀값을 암호화해 저장한다(kind별 1개). 허용 외 kind나 키 사용 불가면 ValueError."""
    if kind not in KINDS:
        raise ValueError(f"허용되지 않은 종류: {kind} (허용: {', '.join(KINDS)})")
    f = _fernet()
    if f is None:
        raise ValueError("금고를 열 수 없습니다(마스터키 생성/접근 실패).")
    data = _load()
    data[kind] = f.encrypt(value.encode()).decode()
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def get(kind: str) -> str | None:
    """비밀값을 복호화해 돌려준다. 미등록·키없음·복호화실패면 None(안전 폴백)."""
    f = _fernet()
    if f is None:
        return None
    token = _load().get(kind)
    if not token:
        return None
    try:
        return f.decrypt(token.encode()).decode()
    except InvalidToken:
        return None  # 키 교체 등으로 복호화 불가 — 비밀 노출 대신 미등록으로 취급
