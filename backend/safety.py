"""횡단 안전 정책 + 헬퍼 — 결정적 코드, 모델 판단 아님(§4·§11, 부록A).

안전 한계선은 harness가 강제한다. 백엔드가 신뢰 경계라(content.js는 우회 가능) 게이트는 여기에 둔다.
도메인 allowlist만 env로 설정 가능(범용 확장 대비, `<all_urls>` 금지 — §15-5). 나머지는 편집 가능한 상수.
"""

import os
import re
from urllib.parse import urlparse

# 도메인 allowlist — 호스트 접미사. env ALLOWED_DOMAINS(쉼표 구분)로 덮어쓸 수 있다(기본 scourt).
# 빈 값(.env.example를 그대로 복사한 경우)은 미설정으로 보고 기본값으로 떨어진다 — allowlist가
# 비면 모든 이동이 막혀 버리는 사고 방지.
ALLOWED_DOMAINS = tuple(
    d.strip() for d in (os.getenv("ALLOWED_DOMAINS") or "scourt.go.kr").split(",") if d.strip()
)

# 비가역 액션 라벨 키워드 — 클릭 대상 라벨에 이게 있으면 성숙도/확신도 무관 강제 승인(§4·§10).
CRITICAL_KEYWORDS = (
    "제출",
    "납부",
    "결제",
    "취하",
    "송달",
    "신청",
    "삭제",
    "등록",
    "발송",
    "접수",
)


def label_for_index(obs: dict | None, index: int | None) -> str:
    """관측 elements에서 `[index]` 줄의 설명(태그+속성+라벨)을 꺼낸다. 없으면 빈 문자열.

    줄 형식(content.js): `*[12]<button name="사건검색"> 사건검색` — *는 새 요소 표시.
    크리티컬 판정은 라벨뿐 아니라 name 속성도 봐야 하므로 `]` 뒤 전체를 반환한다."""
    if not obs:
        return ""
    pat = re.compile(rf"^\*?\[{index}\](.*)$", re.M)
    for line in obs.get("elements") or []:
        m = pat.match(line)
        if m:
            return m.group(1).strip()
    return ""


def is_critical(label: str) -> bool:
    """라벨에 비가역 액션 키워드가 포함되면 True(강제 승인 대상)."""
    return any(kw in label for kw in CRITICAL_KEYWORDS)


def domain_allowed(url: str) -> bool:
    """url 호스트가 allowlist 접미사에 매칭되면 True. 파싱 실패/스킴 없는 url은 False."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)
