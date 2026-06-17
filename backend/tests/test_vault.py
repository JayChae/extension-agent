"""Phase 9B 자동 검증 — 🔐 자격증명 금고 + 네이티브 다이얼로그(가짜 모델 + 가짜 브라우저).

금고 암호화 라운드트립·at-rest 암호화·안전 폴백, fill_credential이 모델에 값을 안 주고 금고에서
직접 꺼내 채움(감사 로그에 평문 비밀값 부재), 다이얼로그 관측 노출을 결정적·무비용으로 돌린다.
"""

import json

import audit
import main
import vault
from agent import render_observation
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from test_loop import model_from, ok_obs

client = TestClient(main.app)

SECRET = "courtPIN-9876"  # 비밀값 대역 — 모델·관측·로그 어디에도 평문으로 남으면 안 됨


def _vault(monkeypatch, tmp_path, key=None):
    """임시 키·임시 경로로 금고를 격리한다. 키 생략 시 새 Fernet 키(env 우선 경로)."""
    monkeypatch.setattr(vault, "VAULT_KEY", key if key is not None else Fernet.generate_key().decode())
    monkeypatch.setattr(vault, "KEY_PATH", tmp_path / "master.key")
    monkeypatch.setattr(vault, "SECRETS_PATH", tmp_path / "secrets.json")


# ---- 금고 단위 -----------------------------------------------------------------
def test_vault_roundtrip(monkeypatch, tmp_path):
    _vault(monkeypatch, tmp_path)
    vault.put("cert_pin", SECRET)
    assert vault.get("cert_pin") == SECRET


def test_vault_encrypted_at_rest(monkeypatch, tmp_path):
    _vault(monkeypatch, tmp_path)
    vault.put("cert_pin", SECRET)
    raw = vault.SECRETS_PATH.read_text(encoding="utf-8")
    assert SECRET not in raw  # 디스크엔 암호문만


def test_vault_missing_kind(monkeypatch, tmp_path):
    _vault(monkeypatch, tmp_path)
    assert vault.get("cert_pin") is None  # 미등록


def test_vault_rejects_unknown_kind(monkeypatch, tmp_path):
    _vault(monkeypatch, tmp_path)
    try:
        vault.put("evil_key", "x")
        assert False, "허용 외 kind를 받아들이면 안 됨"
    except ValueError:
        pass


def test_vault_autogen_key(monkeypatch, tmp_path):
    # env 키가 없으면 KEY_PATH에 마스터키를 자동 생성·재사용한다(설정 불필요).
    _vault(monkeypatch, tmp_path, key="")
    vault.put("cert_pin", SECRET)
    assert (tmp_path / "master.key").exists()  # 키 자동 생성됨
    assert vault.get("cert_pin") == SECRET  # 같은 키로 복호화


def test_vault_no_key_safe(monkeypatch, tmp_path):
    # 키를 전혀 만들 수 없는 상태(쓰기 실패 등)면 비활성 — 예외 대신 안전 폴백.
    monkeypatch.setattr(vault, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(vault, "_key", lambda: None)
    assert vault.get("cert_pin") is None
    try:
        vault.put("cert_pin", SECRET)
        assert False, "키 없이 저장되면 안 됨"
    except ValueError:
        pass


# ---- fill_credential 풀루프(WS): 모델은 kind만, 금고가 값을 채운다 -------------
def test_fill_credential_flow(monkeypatch, tmp_path):
    _vault(monkeypatch, tmp_path)
    vault.put("cert_pin", SECRET)
    monkeypatch.setattr(audit, "LOG_PATH", tmp_path / "audit.jsonl")
    steps = [
        ("perceive", {}),
        ("fill_credential", {"index": 1, "kind": "cert_pin"}),  # 모델은 종류만 — 값 모름
        ("done", {"result": "로그인 완료"}),
    ]
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: steps[i]))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "공동인증서로 로그인해줘"})
        assert ws.receive_json()["type"] == "command"  # perceive
        ws.send_json(
            {"type": "observation", "observation": ok_obs(elements=['[1]<input name="인증서비밀번호">'])}
        )
        # fill_credential → 금고에서 꺼낸 비밀값을 담은 type command가 나간다(모델이 보낸 적 없음).
        cmd = ws.receive_json()
        assert cmd["type"] == "command"
        act = cmd["action"]
        assert act["kind"] == "type" and act["index"] == 1
        assert act["text"] == SECRET  # harness가 금고에서 꺼냄
        assert act["secret"] is True  # content가 note에 echo 안 하게
        ws.send_json({"type": "observation", "observation": ok_obs(note="입력: [1] (비밀값)")})
        echo = ws.receive_json()
        assert echo["type"] == "backend_echo" and "완료" in echo["text"]

    # 감사 로그: 평문 비밀값은 어디에도 없고, fill_credential 이벤트는 종류 라벨만 남는다.
    events = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(SECRET not in json.dumps(e, ensure_ascii=False) for e in events)
    fc = [e for e in events if e["event"] == "fill_credential"]
    assert fc and fc[0]["kind"] == "cert_pin" and "text" not in fc[0]


# ---- 사이드패널 등록(WS): 값은 백엔드 금고까지만, 로그엔 종류만 ----------------
def test_register_credential_ws(monkeypatch, tmp_path):
    _vault(monkeypatch, tmp_path)
    monkeypatch.setattr(audit, "LOG_PATH", tmp_path / "audit.jsonl")
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "register_credential", "kind": "cert_pin", "value": SECRET})
        echo = ws.receive_json()
        assert echo["type"] == "backend_echo" and "등록됨" in echo["text"] and "cert_pin" in echo["text"]
    assert vault.get("cert_pin") == SECRET  # 금고에 들어감
    # 감사 로그: 종류 라벨만 — 평문 비밀값은 어디에도 없다.
    events = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e["event"] == "credential_registered" and e.get("kind") == "cert_pin" for e in events)
    assert all(SECRET not in json.dumps(e, ensure_ascii=False) for e in events)


def test_register_credential_rejects_bad_kind(monkeypatch, tmp_path):
    _vault(monkeypatch, tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "register_credential", "kind": "evil_key", "value": "x"})
        echo = ws.receive_json()
        assert echo["type"] == "backend_echo" and "실패" in echo["text"]
    assert vault.get("cert_pin") is None  # 아무것도 저장 안 됨


# ---- 네이티브 다이얼로그 관측 노출 --------------------------------------------
def test_dialog_rendered_in_observation():
    obs = ok_obs()
    obs["dialogs"] = [{"kind": "confirm", "message": "제출하시겠습니까?"}]
    fenced = render_observation(obs)
    assert "<UNTRUSTED_PAGE_DATA>" in fenced  # 펜스 안(신뢰 불가 데이터)
    assert "네이티브 다이얼로그" in fenced and "제출하시겠습니까?" in fenced
