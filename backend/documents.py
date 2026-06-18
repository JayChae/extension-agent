"""문서(PDF) 열람 — content가 받아온 PDF 바이트를 텍스트로 뽑아 관측에 싣는다(§3, §10).

content script가 페이지 출처(scourt)에서 fetch한 PDF를 base64로 보내면 여기서 디코드·파싱한다.
파싱(복잡·위험)은 전부 백엔드에 두고 content는 바이트만 넘긴다("content 얇게" 원칙, §3).
추출 텍스트는 신뢰불가 페이지 데이터 → render_observation의 <UNTRUSTED_PAGE_DATA> 펜스로 감싸진다.
"""

import base64
import binascii

import fitz  # pymupdf

import audit
import safety

MAX_BYTES = 10 * 1024 * 1024  # 10MB — 과대 PDF 거부(WS·모델 컨텍스트 보호). content도 같은 상한.
MAX_PAGES = 30  # 페이지 상한
MAX_CHARS = 12_000  # 누적 텍스트 상한 — 초과 시 잘라내고 truncated 표시


def _extract_text(data: bytes) -> tuple[str, int, bool]:
    """PDF 바이트에서 텍스트를 뽑는다 → (text, n_pages, truncated)."""
    with fitz.open(stream=data, filetype="pdf") as doc:
        n_pages = doc.page_count
        chunks: list[str] = []
        total = 0
        truncated = n_pages > MAX_PAGES
        for i in range(min(n_pages, MAX_PAGES)):
            t = doc[i].get_text()
            if total + len(t) > MAX_CHARS:
                chunks.append(t[: MAX_CHARS - total])
                truncated = True
                break
            chunks.append(t)
            total += len(t)
    return "".join(chunks).strip(), n_pages, truncated


def extract_into(obs: dict) -> dict:
    """관측에 실린 PDF base64를 텍스트로 바꿔 obs["document"]에 채워 돌려준다.

    실패·거부 시 obs를 에러 관측으로 치환한다. 평문 내용은 감사 로그에 남기지 않는다.
    """
    if not obs.get("ok"):
        return obs
    doc = obs.get("document")
    if not isinstance(doc, dict) or not doc.get("b64"):
        return {"ok": False, "error": "문서 데이터가 비어 있다 — 다운로드에 실패했을 수 있다."}

    url = doc.get("source_url") or ""
    # 🔒 도메인 재검증(§11) — content가 보냈더라도 백엔드가 신뢰 경계. 허용 외면 내용 폐기.
    if not safety.domain_allowed(url):
        return {"ok": False, "error": f"허용 도메인 아님: {url} — 이 문서는 읽지 않는다."}

    # base64는 ~4/3로 부푼다. 디코드(전체 메모리 할당) 전에 문자열 길이로 먼저 상한을 건다.
    if len(doc["b64"]) > MAX_BYTES * 4 // 3 + 8:
        return {"ok": False, "error": f"문서가 너무 큼(상한 {MAX_BYTES} bytes)."}
    try:
        data = base64.b64decode(doc["b64"], validate=True)
    except (binascii.Error, ValueError):
        return {"ok": False, "error": "문서 디코드 실패(손상된 데이터)."}
    if len(data) > MAX_BYTES:
        return {"ok": False, "error": f"문서가 너무 큼({len(data)} bytes, 상한 {MAX_BYTES})."}
    if not data.startswith(b"%PDF"):  # 세션 만료 시 HTML 200 등 — PDF가 아니면 거짓 추출 대신 명확히 실패
        return {"ok": False, "error": "PDF가 아니다(로그인 만료 등으로 다른 페이지가 왔을 수 있다)."}

    try:
        text, pages, truncated = _extract_text(data)
    except Exception as e:  # 손상·암호화 PDF 등 — 깔끔히 실패 보고(추측 금지)
        return {"ok": False, "error": f"PDF 파싱 실패: {e}"}

    audit.log("read_document", url=url, bytes=len(data), pages=pages, chars=len(text))  # 내용 미기록

    result = {
        "ok": True,
        "page": obs.get("page"),
        "document": {
            "source_url": url,
            "pages": pages,
            "chars": len(text),
            "truncated": truncated,
            "text": text,
        },
    }
    if not text:
        result["note"] = "문서에 추출 가능한 텍스트가 없음(스캔 PDF일 수 있음 — OCR 미지원)."
    return result
