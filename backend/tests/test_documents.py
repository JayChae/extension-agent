"""Phase 10 자동 검증 — 문서(PDF) 다운로드→읽기→행동을 가짜 모델·가짜 브라우저로 결정적 검증.

- PDF는 테스트 안에서 pymupdf로 즉석 생성(별도 픽스처 파일 불필요).
- documents.extract_into() 단위 검증(도메인 거부·빈/스캔 PDF·상한·감사로그) + WS 풀루프 통합 검증.
"""

import base64

import documents
import fitz  # pymupdf
import main
from agent import render_observation
from test_loop import client, drive, model_from, ok_obs


# ---- 헬퍼 --------------------------------------------------------------------
def make_pdf(text: str) -> bytes:
    """주어진 텍스트 한 줄이 든 1쪽 PDF 바이트를 만든다.

    주의: pymupdf 기본 폰트엔 한글 글리프가 없어 테스트 PDF엔 ASCII만 쓴다(실제 scourt PDF는
    한글 폰트가 임베드돼 추출이 정상 — 이건 픽스처 한계지 제품 한계가 아니다)."""
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def b64_of(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def doc_obs(b64: str, source_url: str = "https://ecfs.scourt.go.kr/doc/123.pdf") -> dict:
    """content가 PDF를 받아 보낸 관측 모양."""
    return {
        "ok": True,
        "page": {"url": "https://ecfs.scourt.go.kr/x", "title": "전자소송"},
        "document": {"source_url": source_url, "content_type": "application/pdf", "b64": b64},
    }


# ---- T1: PDF 텍스트가 펜스 안으로 들어온다(모델이 보는 입력) ----------------------
def test_extract_and_render_puts_text_in_fence():
    obs = doc_obs(b64_of(make_pdf("CASE 2024GADAN99999 plaintiff Hong")))
    out = render_observation(documents.extract_into(obs))
    assert out.startswith("<UNTRUSTED_PAGE_DATA>") and out.endswith("</UNTRUSTED_PAGE_DATA>")
    assert "2024GADAN99999" in out  # PDF 내용이 모델 입력에 실린다
    assert "문서(PDF)" in out


# ---- T2: scourt 밖 도메인이면 내용 폐기 ----------------------------------------
def test_offdomain_document_rejected():
    obs = doc_obs(b64_of(make_pdf("secret")), source_url="https://evil.example.com/x.pdf")
    res = documents.extract_into(obs)
    assert res["ok"] is False
    assert "허용 도메인" in res["error"]
    assert "document" not in res  # 내용 안 실림


# ---- T3: 빈/스캔 PDF → "텍스트 없음" 안내(환각 안 함) ---------------------------
def test_empty_pdf_notes_no_text():
    doc = fitz.open()
    doc.new_page()  # 텍스트 없는 빈 페이지(스캔 PDF처럼 텍스트 레이어 없음)
    data = doc.tobytes()
    doc.close()
    res = documents.extract_into(doc_obs(b64_of(data)))
    assert res["ok"] is True
    assert res["document"]["text"] == ""
    assert "OCR 미지원" in res.get("note", "")


# ---- T4: 텍스트 상한 초과 → 잘라내고 truncated ---------------------------------
def test_long_text_truncated(monkeypatch):
    monkeypatch.setattr(documents, "MAX_CHARS", 10)
    res = documents.extract_into(doc_obs(b64_of(make_pdf("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))))
    assert res["document"]["truncated"] is True
    assert res["document"]["chars"] <= 10


# ---- T5: 크기 상한 초과 → 거부 ------------------------------------------------
def test_oversized_rejected(monkeypatch):
    monkeypatch.setattr(documents, "MAX_BYTES", 100)
    res = documents.extract_into(doc_obs(b64_of(make_pdf("hi"))))
    assert res["ok"] is False
    assert "너무 큼" in res["error"]


# ---- T6: 손상된 base64 → 깔끔히 실패 ------------------------------------------
def test_bad_base64_rejected():
    res = documents.extract_into(doc_obs("!!!not-base64!!!"))
    assert res["ok"] is False
    assert "디코드" in res["error"]


# ---- T6b: PDF가 아님(세션 만료 시 HTML 200 등) → 거짓 추출 대신 명확히 실패 -------
def test_non_pdf_rejected():
    res = documents.extract_into(doc_obs(b64_of(b"<html><body>login required</body></html>")))
    assert res["ok"] is False
    assert "PDF가 아니다" in res["error"]


# ---- T7: 감사 로그에 내용은 안 남고 char 수만 ----------------------------------
def test_audit_records_no_content(monkeypatch, tmp_path):
    import audit

    log = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "LOG_PATH", log)
    documents.extract_into(doc_obs(b64_of(make_pdf("SECRETCASE55555"))))
    body = log.read_text(encoding="utf-8")
    assert "read_document" in body
    assert "SECRETCASE55555" not in body  # 내용은 로그에 없음
    assert '"chars"' in body


# ---- T8: WS 풀루프 — 다운로드→읽기→그 내용 근거로 행동→done ---------------------
def test_full_loop_download_read_act(monkeypatch):
    steps = [
        ("perceive", {}),
        ("read_document", {"index": 3}),
        ("type_text", {"index": 1, "text": "2024가단77777"}),  # PDF에서 읽은 값으로 행동
        ("done", {"result": "문서 읽고 입력 완료"}),
    ]
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: steps[i]))
    observations = [
        ok_obs(elements=['[1]<input name="사건번호">', '[3]<a href="...pdf"> 판결문.pdf']),
        doc_obs(b64_of(make_pdf("CASE 2024GADAN77777"))),  # read_document 응답
        ok_obs(note="입력 완료"),
    ]
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "판결문 보고 사건번호 입력해줘"})
        result = drive(ws, observations)
    assert result.startswith("완료:")
    assert "문서 읽고 입력 완료" in result


# ---- T9: read_document가 화면 상태를 오염시키지 않는다(크리티컬 게이트 유지) ------
def test_read_document_does_not_poison_critical_gate(monkeypatch):
    # perceive(제출 버튼 화면) → read_document → click(제출). read_document 관측엔 elements가 없는데,
    # 그게 last_observation을 덮으면 제출 라벨을 못 읽어 승인을 건너뛴다. 덮지 않아야 게이트가 산다.
    steps = [
        ("perceive", {}),
        ("read_document", {"index": 3}),
        ("click", {"index": 2}),  # 제출 → 게이트가 떠야 한다
        ("done", {"result": "제출 완료"}),
    ]
    monkeypatch.setattr(main, "MODEL", model_from(lambda i: steps[i]))
    submit_screen = ok_obs(elements=['[1]<input name="내용">', '[2]<button name="제출"> 제출'])
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "문서 보고 제출"})
        assert ws.receive_json()["type"] == "command"  # perceive
        ws.send_json({"type": "observation", "observation": submit_screen})
        assert ws.receive_json()["type"] == "command"  # read_document
        ws.send_json({"type": "observation", "observation": doc_obs(b64_of(make_pdf("CASE 1")))})
        gate = ws.receive_json()  # click(제출) → 승인 카드(오염됐다면 그냥 click command가 나갔을 것)
        assert gate["type"] == "approve_action"
        assert "제출" in gate["label"]
        assert gate["index"] == 2
