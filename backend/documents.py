"""문서(PDF) 열람 — content가 받아온 PDF 바이트를 구조 보존 텍스트로 뽑아 관측에 싣는다(§3, §10·§11).

content script가 페이지 출처(scourt)에서 fetch한 PDF를 base64로 보내면 여기서 디코드·파싱한다.
파싱(복잡·위험)은 전부 백엔드에 두고 content는 바이트만 넘긴다("content 얇게" 원칙, §3).
추출은 opendataloader-pdf(Java JAR을 subprocess로 호출)로 표·구조를 보존(markdown/html). 추출 텍스트는
신뢰불가 페이지 데이터 → render_observation의 <UNTRUSTED_PAGE_DATA> 펜스로 감싸진다. 펜스를 만드는
쪽(백엔드)이 책임지고 펜스 토큰을 본문에서 제거한다 — PDF 텍스트는 content.js stripMarkers를 안 거치는
경로라(content는 바이트만 넘김) 악성 PDF가 닫는 토큰을 박아 지시를 주입하는 걸 여기서 막아야 한다.
"""

import base64
import binascii
import glob
import os
import re
import tempfile

import opendataloader_pdf

import audit
import safety

MAX_BYTES = 10 * 1024 * 1024  # 10MB — 과대 PDF 거부(WS·모델 컨텍스트 보호). content도 같은 상한.
MAX_CHARS = 12_000  # 누적 텍스트 상한 — 초과 시 앞부분만 남기고 truncated 표시(뒤=결론은 pages 인자로)

# render_observation의 <UNTRUSTED_PAGE_DATA> 펜스를 깨는 토큰을 본문에서 제거(content.js stripMarkers와
# 동일 정규식). PDF 텍스트는 content를 안 거치므로 여기가 유일한 방어 지점이다.
_FENCE = re.compile(r"</?UNTRUSTED_PAGE_DATA>", re.IGNORECASE)
_PAGE_SEP = "\f"  # 페이지 경계 표식 — 쪽수를 센 뒤 본문에서 제거(opendataloader page separator)
_ALLOWED_FORMATS = {"markdown", "html"}


def _extract_text(data: bytes, fmt: str, pages: str | None) -> tuple[str, int, bool]:
    """PDF 바이트 → (text, n_pages, truncated). opendataloader로 구조(표 등)를 보존해 추출.

    opendataloader는 바이트/스트림 API가 없고 output_dir에 파일을 쓴다 → 임시폴더에 ASCII 고정명으로
    쓰고(한글 경로 우회 회피) 변환 후 결과 파일을 읽는다. 폴더는 with로 자동 정리.
    """
    ext = "md" if fmt == "markdown" else "html"
    with tempfile.TemporaryDirectory() as d:
        inp = os.path.join(d, "doc.pdf")
        out = os.path.join(d, "out")
        os.makedirs(out)
        with open(inp, "wb") as f:
            f.write(data)
        opendataloader_pdf.convert(
            input_path=[inp],
            output_dir=out,
            format=fmt,
            image_output="off",
            quiet=True,
            pages=pages,  # "1-3"·"2,5"꼴(없으면 전체) — 모델이 결론(문서 끝)을 넘겨 읽게
            markdown_page_separator=_PAGE_SEP,
            html_page_separator=_PAGE_SEP,
        )
        # 출력은 입력 stem 기준 doc.{ext}이지만, 명명이 바뀌어도 빈 텍스트(거짓 "스캔 PDF")로
        # 조용히 무너지지 않게 해당 확장자를 glob으로 집는다.
        matches = glob.glob(os.path.join(out, f"*.{ext}"))
        text = ""
        if matches:
            with open(matches[0], encoding="utf-8") as f:
                text = f.read()
    n_pages = text.count(_PAGE_SEP)  # 구분자 1개 = 추출된 페이지 1개
    # 펜스 토큰 제거(🔒) → 페이지 표식 제거 순. 둘 다 지운 뒤 상한을 건다.
    text = _FENCE.sub("", text.replace(_PAGE_SEP, "")).strip()
    truncated = len(text) > MAX_CHARS  # 슬라이스는 상한 이하면 무동작이라 분기 불필요
    return text[:MAX_CHARS], n_pages, truncated


def extract_into(obs: dict, fmt: str = "markdown", pages: str | None = None) -> dict:
    """관측에 실린 PDF base64를 텍스트로 바꿔 obs["document"]에 채워 돌려준다.

    실패·거부 시 obs를 에러 관측으로 치환한다. 평문 내용은 감사 로그에 남기지 않는다.
    fmt=markdown|html(그 외 거부), pages="1-3"꼴(없으면 전체).
    """
    if not obs.get("ok"):
        return obs
    if fmt not in _ALLOWED_FORMATS:
        return {"ok": False, "error": f"지원 형식 아님(markdown|html): {fmt}"}
    if pages and not re.fullmatch(r"[\d,\s-]+", pages):  # subprocess에 임의 문자열을 넘기지 않는다
        return {"ok": False, "error": f"잘못된 페이지 범위: {pages} (예: 1-3 또는 2,5)"}
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
        text, pages_n, truncated = _extract_text(data, fmt, pages)
    except Exception as e:  # 손상·암호화 PDF, Java 런타임 부재 등 — 깔끔히 실패 보고(추측 금지)
        return {"ok": False, "error": f"PDF 파싱 실패: {e}"}

    audit.log("read_document", url=url, bytes=len(data), pages=pages_n, chars=len(text))  # 내용 미기록

    result = {
        "ok": True,
        "page": obs.get("page"),
        "document": {
            "source_url": url,
            "pages": pages_n,
            "chars": len(text),
            "truncated": truncated,
            "text": text,
        },
    }
    if not text:
        result["note"] = "문서에 추출 가능한 텍스트가 없음(스캔 PDF일 수 있음 — OCR 미지원)."
    return result
