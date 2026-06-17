# Architecture — "AI 신입사원" 웹 자동화 에이전트

> **이 문서가 단일 진실 원천(Source of Truth)입니다.** 앞으로의 개발은 이 문서를 기준으로 합니다.
> 📄 처음 보거나 빠르게 훑고 싶다면 → [overview.md](overview.md) (2분 요약)
> 신입 직원처럼 **가르치면 배우고 → 모르면 묻고 → 기억하고 → 점점 혼자 하는** 웹 업무 자동화 에이전트.
> 대상 사용자 예: 송무팀이 대한민국 법원 **전자소송 사이트**(주 사이트 `ecfs.scourt.go.kr`, 도메인군 `*.scourt.go.kr` — 로그인·인증 등 하위도메인 포함) 업무를 가르쳐 자동화.

---

## 목차

1. 한눈에 — 무엇을, 왜
2. 시스템 아키텍처 (부품 + 데이터 흐름)
3. 지각(Perception) — 화면을 어떻게 읽나
4. 행동(Action) — 어떻게 클릭/입력하나
5. 에이전트 도구 (= 권한 전부)
6. Human-in-the-Loop — "막히면 묻는다"
7. 학습 루프 — 시스템의 심장
8. 조립식 스킬 & 토큰 관리
9. 메모리 모델 (파일 레이아웃 + 실제 예시)
10. 자율성 졸업 — "점점 혼자 한다"
11. 보안 · 규정 (로그인/인증서 · 인젝션 · 감사 · PIPA)
12. 기술 스택 · 모델 · 비용
13. MVP 범위 (가장 작은 1차)
14. 위험과 한계
15. 결정이 필요한 열린 질문
- 부록 A. 주요 설계 결정과 이유
- 부록 B. 공식문서/연구 근거

---

## 1. 한눈에 — 무엇을, 왜

### 한 줄

**단일 AI 에이전트 루프**(상태머신·그래프 없음)를 두뇌로, **크롬 사이드패널**을 그 거주지이자 사수 콕핏으로, **content script**를 "손"으로, **FastAPI 백엔드**를 비서·금고로 둔다. 코드는 최소, 판단과 권한은 모델에게. 그리고 **자동 학습 루프**(시연→증류→교정→승인→졸업)가 이 시스템의 심장이다.

### 설계 철학 — "오케스트레이션을 코딩하지 말고, 에이전트에게 권한을 줘라"

"코드는 최대한 단순 / 에이전트엔 더 많은 권한"이라는 두 목표는 같은 결론입니다.

- **업무 분기 로직을 코드에 박지 않는다.** "확신도 < 0.85면 사람에게 묻기" 같은 if문 없음. *언제 물어볼지조차 모델이 도구로 스스로 결정.* (단, *안전 가드레일*은 예외 — 스텝 예산·무진전 감지·연속 실패·졸업 카운터는 일부러 코드가 강제하는 if문이다. 즉 **업무 판단은 모델이, 안전 한계선은 코드가**.)
- **상태머신(그래프)을 만들지 않는다.** Pydantic AI 공식문서: *"그래프는 못총(nail gun)이다 — 필요할 때가 아니면 쓰지 마라."* `agent.run()`이 이미 `모델 → 도구 → 결과` 루프를 내부에서 돈다.
- **연구의 정설과 일치.** AgentOccam 논문: 그래프·스캐폴딩 없이 관측/행동 공간을 다듬기만 해도 +161%. 똑똑함은 노드 머신이 아니라 *지각의 질 + 기억*에서 나온다.

> 우리가 직접 짜는 코드(=harness: 모델의 판단을 실제 동작으로 옮기고 안전을 강제하는 AI가 아닌 일반 코드)는 *지각 스냅샷 만들기 · 파일/git I/O · 안전 게이트 · 성숙도 카운터 · 헛돎 가드레일(스텝 예산·무진전·연속 실패)*뿐. **업무에 관한 모든 판단**은 모델이 도구로 소유하고, **안전·종료 한계선**만 코드가 강제한다.

---

## 2. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│  브라우저 (송무 직원 PC) — ecfs.scourt.go.kr 탭 / 팝업 / iframe   │
│   ▲ DOM 읽기 · 클릭/입력 실행 · 시연 녹화                          │
│  [Content Script — "손"]  자동 주입, isolated world, 얇음          │
└───┼───────────────────────────────────────────────────────────────┘
    │ chrome.runtime 메시징
┌───▼───────────────────────────────────────────────────────────────┐
│  크롬 익스텐션 (MV3)                                                │
│  ┌──────────────────────┐   ┌─────────────────────────────────┐    │
│  │ Service Worker       │   │  Side Panel — "두뇌의 거주지"    │    │
│  │ (얇은 이벤트 라우터)  │◄─►│  · 사수 채팅 / 승인 카드          │    │
│  │ 추론 루프 절대 없음   │   │  · "Show me" 시연 버튼            │    │
│  └──────────────────────┘   │  · 스킬 성숙도 대시보드          │    │
│                             │  · STOP 킬스위치 · WebSocket     │    │
│                             └───────────────┬─────────────────┘    │
└─────────────────────────────────────────────┼──────────────────────┘
                          WebSocket (양방향)   │
┌─────────────────────────────────────────────▼──────────────────────┐
│  FastAPI 백엔드 — "사무실 / 금고"                                    │
│   · Anthropic API 키 (시크릿 매니저, 익스텐션엔 절대 없음)          │
│   · 단일 Pydantic AI Agent.run()  ← 오케스트레이션 전부             │
│   · 학습 파이프라인 (시연→SOP 증류 · 교정→레슨 화해)                │
│   · 성숙도 엔진 (졸업 카운터)                                       │
│   · 🔒 신뢰 안전 게이트 (크리티컬 액션 allowlist · 도메인 · 감사)    │
│   · 🔐 자격증명 금고 (로그인·인증서 비밀값, 암호화)                  │
│   · 메모리 저장소 (git 버전관리 파일 + 벡터 인덱스)                 │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ pydantic-ai-slim[anthropic]
                  ┌────────▼─────────┐
                  │  Claude          │  Sonnet 4.6 (스텝 루프)
                  │  + 프롬프트 캐싱 │  Opus 4.8 (교육·크리티컬)
                  └──────────────────┘
```

### 컴포넌트별 책임

| 컴포넌트 | 책임 | 왜 여기인가 |
|---|---|---|
| **사이드패널** (두뇌 거주지) | WebSocket, 사수 채팅, `ask_human`/승인 카드, "Show me" 녹화 버튼, **성숙도 대시보드**, STOP 킬스위치, 라이브 상태 | 모든 chrome API 접근 + idle 종료되지 않는 진짜 문서. SW의 30초/5분 함정 회피 |
| **서비스워커** (얇은 라우터) | 툴바 클릭→패널 오픈, 탭/팝업을 tabId로 등록, 킬스위치 릴레이. **추론 루프 없음** | SW는 30초 idle/5분 요청 한계로 LLM 루프 못 버팀 |
| **content script** (손) | `all_frames:true`로 모든 법원 탭/팝업/iframe 자동 주입. ① 인덱스 요소 목록 생성 ② 인덱스 요소 click/type 실행 ③ 시연 녹화 | isolated world라 DOM+메시징만 → 얇게 유지 강제. password/인증서 필드 직접 읽기 금지 |
| **chrome.debugger 에스컬레이션** | 합성 이벤트가 `isTrusted=false`로 거부될 때만 신뢰 입력 발생 | "디버깅 중" 배너 세금 → 기본 경로 아님 |
| **FastAPI 백엔드** | API 키, `agent.run()`, message_history 직렬화(pause/resume), 학습 파이프라인, 성숙도, 🔒안전 게이트, 🔐자격증명 금고, 감사 로그 | 시크릿은 백엔드에만. 익스텐션 번들은 누구나 뜯어봄 |
| **단일 Pydantic AI Agent** | `agent.run()`이 관측→사고→행동 루프 전체를 내부 실행. 노드·상태머신 없음 | 모델이 모든 지능을 도구로 소유 |
| **메모리 저장소** | git 버전관리 SOP/스킬/상식/케이스 + 벡터 인덱스(섹션 9) | git이 diff/history/PR을 무료 제공 |
| **🔒 신뢰 안전 게이트** | 비가역 액션 allowlist + `always_confirm` → 강제 승인. 도메인 allowlist, CAPTCHA→인간, PII 리댁션, 해시체인 감사 | 하드코딩, **모델이 절대 우회 불가** |

> 한 스텝의 흐름: ① content script가 인덱스 요소 목록을 사이드패널로 → ② 사이드패널이 WebSocket으로 백엔드에 관측 전송 → ③ 백엔드가 관측+task+SOP를 Claude에 전달, agent가 도구 하나 호출 → ④ 🔒안전 게이트 통과 후 content script가 인덱스→실제 DOM 노드로 실행 → 새 관측이 다음 입력. `ask_human`/크리티컬 액션이면 런이 `DeferredToolRequests`로 종료되고 사람을 기다림.

---

## 3. 지각(Perception) — "DOM 텍스트 우선, 화면은 옵션"

매 스텝 content script(harness)가 **모델이 아니라** 컴팩트한 인덱스 요소 목록을 만든다.

```
[12]<button name="사건검색"> 사건검색
[13]<input name="사건번호">
[14]<select name="사건구분"> 민사
  *[15]<a name="2024가단12345 보기"> 보기      ← * = 직전 스텝 이후 새로 생긴 요소(모달/AJAX 팝업)
```

- **인터랙티브 판정은 태그명이 아니라 멀티시그널 휴리스틱.** scourt는 eXBuilder6/W2UI 사이트라 컨트롤이 `mf_..._btn_`·`_ibx_`·`_sbx_`·`_acp_`·`_rad_`·`_chk_` 식 ID를 단다. 핵심 컨트롤 대부분이 **네이티브 태그**(`<input type=button>`·`<button>`·`<a>`·`<select>`·native input)로 렌더돼 태그만으로도 잘 잡히지만, 커스텀 위젯·라벨까지 포괄하려면 다중 신호가 필요하다. content script는 isolated world라 페이지의 클릭 리스너를 못 보므로(getEventListeners=CDP 전용·페이지 jQuery 접근 불가), **isolated에서 읽히는 신호만** 쓴다: 네이티브 태그 + ARIA 역할·`aria-expanded/pressed` + `tabindex` + `onclick` *속성* + `cursor:pointer` + eXBuilder6 ID/class 접두사.
  - **인덱스는 좁게 유지** — 키워드는 *상호작용* 접두사(`_btn_`/`_ibx_`/`_acp_`/`_sbx_`/`_rad_`/`_chk_`)만 쓰고, 표 뼈대(`_grd_`)나 막연한 `btn`/`search` 같은 광범위 토큰은 제외. 인터랙티브 자손을 가진 컨테이너는 dedup으로 빼 같은 컨트롤을 중복 인덱싱하지 않는다.
  - **W2UI 알림/확인 모달**은 동적 ID라도 `확인` 버튼이 네이티브 input이라 별도 셀렉터 없이 잡힌다.
- **테이블은 Markdown으로 변환** — 각 행의 버튼이 그 행의 사건번호/법원명 텍스트를 달고 있어, 모델이 *텍스트로 행을 먼저 매칭*하고 상대 버튼을 누름.
- **스크린샷은 `see_screen()` opt-in 폴백 전용.** 근거: SeeAct 실험에서 조밀 페이지는 텍스트 선택지 48.9% vs Set-of-Marks 15.1%(텍스트 압승). DOM 텍스트는 캐시가 잘 되고, 1920×1080 스크린샷(~2,691토큰/스텝, 캐시 안 됨)보다 ~10배 저렴.
- **보안 오버레이:** 페이지 콘텐츠는 `<UNTRUSTED_PAGE_DATA>` 마커로 격리, 숨은 지시 벡터(aria-label 악용·visually-hidden CSS·HTML 주석·URL 프래그먼트) 제거, 주민등록번호/당사자명/계좌번호 토큰화, password+인증서 필드 블랭킹(전송 전).

---

## 4. 행동(Action) — "셀렉터를 만들지 마라, 인덱스로 가리켜라"

모델은 **현재 관측의 인덱스로만** 행동하고 셀렉터를 절대 생성하지 않는다(Gemini 설계의 가장 취약한 지점 제거).

- **2단계 실행:** 기본은 content-script 합성 이벤트(빠름, 배너 없음) → 사이트가 untrusted 이벤트를 거부하면 *그 한 액션만* `chrome.debugger`의 `Input.dispatch*`로 에스컬레이션("디버깅 중" 배너를 알려진 세금으로 수용). ✅ **scourt는 합성 이벤트를 수용함이 기존 운영 RPA로 확인됨**(JS `.click()`·jQuery `.trigger('click')` = `isTrusted=false`로 핵심 컨트롤을 매일 구동) → 에스컬레이션은 드문 예외.
- **저장용 요소 IDENTITY는 XPath가 아니라 랭크된 로케이터 사다리:** ① `role+accessible name` ② 안정적 `data-testid/id` ③ label/placeholder ④ visible text+근접 landmark ⑤ 위치 폴백. 실행/리플레이 시 위→아래로 시도, 다 실패하면 LLM이 현재 목록에서 재그라운딩.
- **🔒 크리티컬 액션 하드 게이트:** 비가역 액션(제출/결제/취하) allowlist + SOP `always_confirm` → 신뢰도/성숙도 무관 강제 승인. 실행 직전 *해석된 요소 라벨/역할이 의도와 일치하는지 검증*(악성 페이지가 양성 로케이터를 제출 컨트롤에 겨누는 것 방어).
- **CAPTCHA/안티봇 감지 시 STOP→인간 핸드오프** — 하드코딩, 풀거나 우회하지 않음(ToS 준수, 인젝션 저항).
- **네이티브 JS 다이얼로그(`alert`/`confirm`) 자동 처리:** scourt는 네이티브 경고창을 띄움(기존 RPA가 `switch_to.alert`로 처리). content script(isolated world)는 이 창을 못 닫으므로, 페이지 스크립트 실행 전 **MAIN world에 주입한 작은 훅으로 `window.alert/confirm`을 가로채** 자동 수락 + 메시지를 모델 관측으로 전달. "content script는 얇게(isolated)" 원칙의 *유일한* MAIN-world 예외.

> **Phase 9A 구현 형태(확정) — 횡단 안전 게이트 핵심.** 안전 섹션을 크기 차이로 두 단계로 분할: 9A=결정적 harness 레일 4개, 9B(자격증명 금고·alert/confirm 훅)는 다음 단계. ① **크리티컬 게이트**: 행동이 일반 `click` 도구 하나라 *별도 submit 도구*가 아니라, `click`이 대상 인덱스의 라벨을 **현재 관측 elements에서 직접 읽어**(`safety.label_for_index`, 백엔드가 신뢰 경계) 키워드 allowlist(`CRITICAL_KEYWORDS`: 제출/납부/취하/송달 등)에 걸리면 Pydantic AI **`ApprovalRequired`**(공식문서 확인, `tool_call_approved`로 재진입 판정)를 던진다 → 런이 `DeferredToolRequests.approvals`로 종료 → 사이드패널 승인 카드 → `action_approval`로 무상태 재개(`results.approvals[id]=bool`). 승인 시 **도구 본문이 재실행돼 실제 클릭**(ask_human의 `CallDeferred`는 본문 미재실행과 대비), 거부 시 모델에 통보. *비가역 커밋 지점=제출 클릭*이라 click만 게이트(type/select는 미게이트). `always_confirm` SOP 프론트매터 연동은 후순위 — 키워드 allowlist의 과게이팅은 안전측 실패라 MVP 수용. ② **도메인 allowlist**: `navigate` 도구가 `safety.domain_allowed`로 검사(거부 시 WS 왕복 없이 모델 통보), env `ALLOWED_DOMAINS`로 설정값화(빈 값은 기본 scourt 폴백, `<all_urls>` 금지 §15-5). 익스텐션 `SCOURT_HOST`(content/SW)는 다른 런타임 방어선으로 유지(중복 아님, 방어심층). **레이트 리미터**는 `session._guard_before` 롤링 윈도우(폭주 백스톱). ③ **CAPTCHA**: content.js `detectCaptcha`(recaptcha/hcaptcha/turnstile 셀렉터)가 관측에 `captcha:true`(안전 플래그라 `extra`에 안 덮이게 마지막에 set) → `_guard_after`가 `CaptchaHandoff`로 중단·핸드오프(풀거나 우회 안 함), 외부 차단이라 SOP 성숙도 미집계.

---

## 5. 에이전트 도구 (= 권한 전부)

| 도구 | 하는 일 |
|---|---|
| `perceive()` | 화면을 바꾸지 않고 인덱스 요소 목록만 다시 읽기(첫 행동·navigate 직후 필수). *Phase 4 구현 시 추가* — 계약상 1 command⇒1 observation이라 첫 관측·재독 채널이 필요 |
| `click(index)` `type(index, text)` `select(index, opt)` | 인덱스 요소 조작 |
| `navigate(url)` `scroll(dir)` `extract(query)` | 이동·스크롤·데이터 추출 |
| `see_screen()` | (옵션) DOM만으로 모호할 때만 스크린샷 |
| `read_sop(path)` | 업무 SOP·재사용 스킬을 *필요할 때* 자가 로드(지연 로딩, 섹션 8) |
| `search_memory(query)` | 레슨·gotchas·과거 케이스 벡터 검색 |
| `fill_credential(index, kind)` | 로그인 ID·비번·**공동인증서 PIN** 입력 — 금고에서 비밀값을 꺼내 직접 입력(모델은 값을 못 봄, `kind`만 지정) |
| **`ask_human(question)`** | 모를 때 사수에게 질문 (멈춤) |
| `propose_sop_diff(diff)` | 배운 걸 노트에 적기 (사람 승인 후 저장). *Phase 6 실현:* 스텝 루프 도구가 아니라 **harness 파이프라인**(시연→메모리 전담 에이전트 증류→`propose_sop` 카드→승인→git)으로 구현 — 시연 중엔 도는 `agent.run()`이 없고, 모델은 쓰기 경로에 못 들어옴(§7·§9) |
| `verify_success(criteria)` | 잘 됐는지 자기검증(졸업 집계용) |
| `done(result)` | 완료 선언 — *Phase 4 구현*: 일반 도구가 아니라 **output 도구**(`ToolOutput`)로 호출되면 런이 끝나고 `result.output`이 됨 |

---

## 6. Human-in-the-Loop — "막히면 묻는다"

확신도 분기도 그래프 노드도 아닌, **Pydantic AI의 네이티브 `deferred tools`로 구현.**

```python
agent = Agent(
    'anthropic:claude-sonnet-4-6',
    output_type=[ActionResult, DeferredToolRequests],  # 일반 결과 OR "사람에게 물음" 신호
    deps_type=Deps,
)

@agent.tool_plain
def ask_human(question: str, options: list[str] | None = None) -> str:
    """모르는 게 있을 때 사수에게 묻는다."""
    raise CallDeferred(metadata={"question": question, "options": options})

@agent.tool(requires_approval=True)   # 크리티컬 액션은 자동 승인 대기
def submit_document(...): ...
```

흐름: ① `ask_human` 호출 → 런이 `DeferredToolRequests`로 깔끔히 종료 → ② 백엔드가 `result.all_messages()`를 직렬화 저장, 질문을 사이드패널로 푸시 → ③ **사람이 분/시간 뒤 답해도 OK**(재개는 무상태 message_history 리플레이, durable 백엔드 불필요) → ④ `agent.run(message_history=..., deferred_tool_results=...)`로 재개.

**세 트리거:**
- **소프트(모델 소유):** 모델이 스스로 불확실해 `ask_human` 호출.
- **하드(우회 불가):** 제출/결제/취하 같은 비가역 액션 + CAPTCHA는 모델 확신도와 무관하게 강제 승인/핸드오프. (로그인·인증서는 비가역이 아니므로 섹션 11 금고로 직접 처리)
- **헛돎 감지(harness 강제, 모델 판단 아님):** ① **스텝 예산** 초과(행복경로 스텝 ×3) ② **무진전** — 최근 N스텝 관측 해시 반복 또는 같은 도구·인덱스 반복 호출 ③ **연속 실패** K회(요소 못 찾음·에러) ④ 전역 wall-clock 타임아웃. 하나라도 걸리면 `ask_human`으로 깔끔히 종료(`DeferredToolRequests`) → 무한루프·헛돎 차단. (대화형 에이전트엔 필수 — 무인 배치 RPA엔 없던 안전망.)

---

## 7. 학습 루프 — 시스템의 심장

**"가르치면 기억하고 점점 잘하게 된다"** — 이 시스템을 RPA가 아니라 AI 신입사원으로 만드는 부분. 비모델 코드는 *파일 I/O + git + 임베딩 검색*뿐, 모든 지능은 강한 모델(Opus 4.8)이 도구로 수행.

> **Phase 6 구현 형태(확정):** 학습은 수행과 **분리된 전용 에이전트**가 한다 — 수행은 Sonnet 스텝 루프(`agent.py`), 학습은 **메모리 전담 Opus 에이전트**(`memory_agent.py`)가 별도로(이 파일이 앞으로 모든 메모리 쓰기 *제안*의 집 — 경로②③ 레슨·화해도 여기 재사용). 시연은 **행동 + 사람의 설명(내레이션)을 함께** 기록해(`{kind:action|note}` 시간순) 모델이 조건·분기를 배우게 한다 — 행동만 녹화하면 분기 없는 매크로가 된다. 증류·승인·기록은 스텝 루프가 아니라 harness 파이프라인(`record_demo`→`distill`→`propose_sop`→`approve_sop`→`memory_store`가 git 원자 커밋).

> **Phase 7 구현 형태(확정):** 경로②·③을 **`ask_human` 한 경로로 합쳤다**(MVP 범위, 사용자 확정) — 사람의 답이 단순 정보든 교정이든 동일하게 레슨 후보다. SOP로 라우팅된 런이 막혀 물으면 그 Q&A를 모아, 런 종료 시 **레슨 전담 에이전트**(`memory_agent.py`의 `lesson_agent`, Opus)가 기존 레슨과 **화해**해 `LessonProposal(ops[])`로 증류 → `propose_lesson` 카드 → 사람 원클릭 승인 → harness(`memory_store.apply_lessons`)가 SOP의 `## 레슨` 섹션에만 병합 후 단일 git 커밋. **화해 매핑:** ADD=새 줄, EDIT=모순 줄 교체(=반복 모순 은퇴, recency 우선), STRENGTHEN=중요도 +1(`(×N)` 표기). 일회성 답이면 `ops=[]`로 카드 자체를 안 띄운다. SOP 초안 "반려+이유→재증류"(경로③의 다른 절반)는 후순위.

### 세 신호 → 증류 → 화해 → 승인 → git

```
 ① "Show me" 시연 1회        ② 막혀서 ask_human → 사람의 답     ③ 승인 카드 "반려+이유"
        │                          │                                 │
        └──────────────┬───────────┴─────────────────────────────────┘
                       ▼
        강한 모델(Opus 4.8)이 증류 → 파라미터화 SOP/레슨
                       ▼
        사람이 SOP diff 원클릭 승인  ← "배웠다" 순간 + 인젝션 방지 잠금
                       ▼
                  git 커밋 → 다음 런에서 로드
```

### 경로 ① 시연으로 가르치기 ("Show me")

사람이 사이드패널 "Show me"를 누르고 업무를 *한 번* 직접 함. content script가 행동마다 기록:

```
1. 클릭: <a> "나의 사건검색"        (주변 단서: 상단 메뉴)
2. 선택: <select 관할법원> → "서울중앙지방법원"
3. 입력: <input 사건번호> → "2024가단12345"
4. 클릭: <button> "검색"
5. (페이지 바뀜) 표에서 "2024가단12345" 행 확인
```

> ⚠️ XPath가 아니라 **요소의 역할+이름+텍스트+주변 단서+입력값**을 기록(나중에 다시 찾으려고).

모델이 증류 → 특정값을 슬롯으로 일반화: `"2024가단12345 입력"` → `"사건번호 칸에 {사건번호} 입력"`. 단, 한 번의 시연은 *모든 분기를 담은 완성 템플릿*이 아니라 **행복경로(happy path) 골격**이다(현실적으로 1회 시연이 분기를 다 담을 수 없음). 증류 시 강한 모델이 **미해결 분기를 SOP에 빈칸(TODO)으로 명시**(예: "결과 0건이면? 여러 건이면? 지원 vs 본원?") → 처음 그 상황을 만나면 `ask_human`. 분기는 경로②·③으로 *운영하며 성숙*한다. → 사람이 SOP 초안 승인, 성숙도 `LEARNING`으로 시작.

### 경로 ② 막히면 물어서 배우기

```
에이전트: (드롭다운에 "수원지방법원"이 없고 "수원지방법원 안산지원"만 있음)
          → ask_human: "이걸 고를까요?"
사람:     "응, 지원까지 정확히 골라야 해."
```
→ 레슨 추가: `⚠️ 법원이 지원이면 '...지원'까지 정확히 선택`. 다음엔 안 물음.

### 경로 ③ 잘못하면 교정해서 배우기

```
에이전트 제안: "2024가단12340 행 읽겠습니다"
사람: [반려] "끝자리가 5야. 2024가단1234'5' 행."
```
→ 레슨 추가: `⚠️ 사건번호는 끝자리까지 완전 일치 행만 선택`.

### 증류는 왜 강한 모델인가

"2024가단12345"는 슬롯으로 빼되 "검색" 버튼 텍스트는 고정해야 함 — 이런 판단은 **Opus 4.8**이 잘함. 매 스텝 단순 클릭/입력은 **Sonnet 4.6**(빠르고 쌈)이 함. 비싼 모델은 *가르칠 때만.*

### 화해 — 왜 그냥 추가만 하면 안 되나

무작정 append하면 노트가 모순 더미로 썩음. 그래서 새 레슨마다 모델이 셋 중 택1:
- **추가(ADD)** — 새 내용 → 새 줄
- **수정(EDIT)** — 기존이 틀림 → 그 줄 교체
- **강화(STRENGTHEN)** — 이미 아는 것 → 중복 없이 중요도 +1

반복 모순되는 레슨은 은퇴(recency 우선).

### 사람의 "OK" 한 번이 두 역할

`propose_sop_diff` → 사이드패널에 변경점(diff) 표시 → 원클릭 승인. 이것이:
- 🟢 **"배웠다" 순간** (원했던 느낌)
- 🔒 **보안 잠금** — 교정은 *사람 승인을 통과해야만* 진짜 규칙이 됨 → 악성 페이지의 숨은 지시가 SOP로 영구 세탁되는 걸 차단.

### 한 SOP의 일생 (섹션 10 졸업과 연결)

```
Day 0   시연 1회        → SOP 생성, LEARNING (매 스텝 물음)
Day 3   몇 번 교정       → 레슨 추가, 덜 물음
Day 7   10번 중 9번 성공 → ASSISTED 승급 (크리티컬만 물음)
Day 20  계속 성공        → SUPERVISED (혼자 + 끝에 확인)
Day 40  검증 성공 누적   → AUTONOMOUS (완전 무인, 예외만)
        ※ 단, '소장 제출' 같은 비가역 행동은 Day 40에도 항상 사람 승인.
```

---

## 8. 조립식 스킬 & 토큰 관리

AI는 **읽는 양만큼 돈·시간**이 들고, 긴 글은 정확도도 떨어짐("건초더미 속 바늘"). → **"지금 필요한 만큼만 보여주기".**

### 업무 = 작은 재사용 스킬의 조립

업무를 한 덩어리로 적지 않고, 작은 스킬로 쪼개 링크로 연결.

```markdown
# 보정명령 확인  (조립 SOP — 짧은 체크리스트)
목표: 보정명령을 확인하고 대응한다
순서:
1. 사건기록을 연다             → 스킬: 사건기록열람
2. 보정 대상 문서 열람·다운로드 → 스킬: 문서열람다운로드   ← 여러 업무가 공유
3. 보정명령 폼을 입력한다       → 스킬: 보정명령폼입력
```

`스킬: 문서열람다운로드`는 다른 파일로 가는 링크. 상세는 그 파일에:

```markdown
# 문서열람다운로드  (원자 스킬 — 재사용 부품)
목표: 특정 문서를 열어 PDF로 받는다
순서:
1. 문서 목록에서 {문서명} 행을 찾는다
2. "열람" 버튼을 누른다 (새 창이 뜸)
3. 새 창에서 "다운로드" 버튼을 누른다
4. 저장 완료를 확인한다
레슨:
- ⚠️ 새 창은 팝업이라 자동으로 안 닫힘. 작업 후 닫아야 함.
```

### 실행할 때 — 필요한 스킬만 읽기 (지연 로딩)

```
업무 "보정명령 확인" 시작
   ├─ 조립 SOP(짧은 체크리스트)만 로드            ← 가벼움
   ├─ [1단계] → read_sop(사건기록열람) → 상세 로드 → 수행 → 끝나면 비움
   ├─ [2단계] → read_sop(문서열람다운로드) → 로드 → 수행 → 비움
   └─ [3단계] → read_sop(보정명령폼입력) → 로드 → 수행 → 비움
```
한 순간 AI가 보는 건 **"조립 SOP(목차) + 지금 하는 스킬 1개"** 뿐. 끝난 단계 상세는 **컨텍스트 편집/압축**으로 비움. 기존 `read_sop` 도구가 그대로 함(우리가 분기 코딩 안 함).

### 배울 때 — "소화 프로세스" (자동 리팩터)

시연을 증류하면서 강한 모델이:
- **① 재사용 감지** — 기존 스킬과 같으면 상세 안 적고 **링크만**
- **② 추출** — 재사용될 묶음인데 스킬이 없으면 **새 스킬 파일로 빼고 링크**
- **③ 인라인 유지** — 이 업무에만 쓰는 한 줄이면 그냥 둠

→ 사람이 diff 승인(새 스킬 파일 + 링크된 조립 SOP 확인). 깊이는 **1~2층까지만** 권장.

### 💎 가장 큰 이득: 한 번 고치면 전부 개선

법원이 다운로드 팝업을 바꿔 깨지면 → `문서열람다운로드.md` **하나만** 고치면 보정명령 확인·소장 확인·준비서면 확인이 **전부 동시에** 고쳐짐(DRY).

### 토큰 절약 장치 종합

| 장치 | 효과 |
|---|---|
| 조립식 스킬 + 지연 로딩 | 지금 단계 스킬만 읽음 |
| 프롬프트 캐싱 | 안정적 프리픽스(시스템 프롬프트·자주 쓰는 스킬) 한 번 저장 후 ~1/10 |
| 컨텍스트 편집/압축 | 끝난 단계 상세·옛 화면 비움 |
| DOM 텍스트 우선 | 무거운 스크린샷 대신 가벼운 글자 목록 |
| 컴팩트 관측 | 매 스텝 *현재 페이지의 인터랙티브 요소*만(전체 HTML 아님) |

---

## 9. 메모리 모델 (git 파일, 별도 DB 불필요)

```
memory/
├─ master_index.json          # 업무·스킬 이름 → 파일 경로 (정확한 라우팅, 모델 추측 아님)
├─ sop/scourt.go.kr/          # ① 조립 SOP: 업무 = 스킬들의 짧은 체크리스트
│   ├─ 보정명령확인.md
│   └─ 소장확인.md
├─ skills/scourt.go.kr/       # ② 원자 스킬: 재사용 부품(상세 단계)
│   ├─ 사건기록열람.md
│   ├─ 문서열람다운로드.md      #   여러 업무가 공유
│   └─ 보정명령폼입력.md
├─ gotchas/scourt.go.kr.md    # 사이트 상식: "세션 10분 타임아웃", "날짜 YYYY.MM.DD"
└─ cases/<사건id>.json         # 과거 처리 기록(append-only)
```

### 메모리 4종류

| 종류 | 사람으로 치면 | 파일 |
|---|---|---|
| **절차 기억 (SOP/스킬)** | "이 업무는 이 순서로" | `sop/`, `skills/` |
| **상식 (gotchas)** | "이 사이트는 원래 이래" | `gotchas/<사이트>.md` |
| **경험 (cases)** | "지난번 이 건 이렇게 처리함" | `cases/<사건id>.json` |
| **목차 (라우터)** | "어떤 일은 어느 파일" | `master_index.json` |

### SOP/스킬 파일의 형식 (프론트매터 + 본문)

```yaml
---
goal: 사건번호로 사건 진행 상태를 조회한다
input_slots:
  - { name: 사건번호, desc: "예: 2024가단12345" }
  - { name: 관할법원, desc: "예: 서울중앙지방법원" }
verify:                                    # 결정적 성공 판정 (자유서술 금지, 4종 중 ≥2종 필수)
  must_appear: ["접수번호 텍스트가 결과영역에 존재"]            # 긍정 신호
  must_match:  ["결과 행 사건번호 == {사건번호} (끝자리까지 완전일치)"]  # 입력-출력 일치
  must_not:    ["'오류'/'권한 없음' 텍스트 또는 네이티브 alert 발생"]   # 부정 신호 부재
  artifact:    []                          # (해당 시) 다운로드 파일 존재 AND 크기>0
maturity:
  level: ASSISTED                          # 현재 성숙도
  success_window: [O,O,X,O,O,O,O,O,O,O]    # 최근 10번 성공/실패
  autonomous_success_count: 3
---
# (NL 스텝들 + 레슨들)
```

핵심 4가지: ① 순서는 **자연어**(셀렉터 아님 → 런타임 재그라운딩) ② `{슬롯}` 빈칸으로 템플릿화 ③ 레슨이 누적 ④ `verify:`로 성공을 **결정적 검증**(졸업 집계의 근거, 자기선언 금지 — 섹션 10).

- **개인 레슨은 자유 기록, 팀 공식 SOP는 git PR 승인**으로만 공유(아무나 팀 노트를 더럽히지 못하게).
- **벡터 인덱스는 레슨/케이스에만**(키 없는 비정형). SOP/스킬은 `master_index.json`으로 결정적 라우팅.
- **`master_index.json`은 "재생성 가능한 파생 캐시"** — 진실의 원천은 SOP/스킬 파일 프론트매터(`goal`/`name`). 갱신은 **사람 승인 트랜잭션 안에서 harness가 원자적으로**(파일 + 인덱스를 같은 git commit) 수행하고 모델이 직접 쓰지 않음(인젝션·불일치 방지). 손상 시 파일 스캔으로 `rebuild_index`, 런 시작 시 정합성 검증(인덱스 ↔ 실제 파일).
- 사람이 마크다운을 직접 열어 고쳐도 됨(git이 이력 남김).

### 런타임에 메모리 쓰는 순서

① `master_index.json`으로 업무→조립 SOP 정확히 라우팅 → ② 관련 gotchas·유사 case 벡터 검색 top-k 회수 → ③ 시스템 프롬프트(캐시 프리픽스)에 SOP+상식 주입 → ④ 단계별로 필요한 스킬을 `read_sop`로 지연 로딩(섹션 8).

---

## 10. 자율성 졸업 — "점점 혼자 한다" (증거 기반)

각 스킬(SOP)은 성숙도 레코드를 가지며 **선언이 아니라 데이터로** 승급.

| 레벨 | 동작 |
|---|---|
| **LEARNING** | 모든 스텝 전 물음 (신입 첫날) |
| **ASSISTED** | 저신뢰 + 모든 크리티컬 스텝만 물음 |
| **SUPERVISED** | 무인 실행, 런 종료 시 인간 사인오프 + 랜덤 스팟체크 |
| **AUTONOMOUS** | 완전 무인, 사람은 예외만 처리 |

- 승급: 최근 N=10 런의 **검증된** 성공률 ≥ T(예 0.9) + 최소 횟수. **실패·반려 시 강등.**
- 성공은 반드시 `verify_success()`로 검증(자기선언 금지) — SOP 프론트매터의 구조화 `verify:`(긍정 `must_appear` / 입출력 일치 `must_match` / 오류 부재 `must_not` / 산출물 `artifact`, **4종 중 ≥2종 필수**, 섹션 9)를 평가. 예: "사건 조회"는 *결과 행 사건번호가 입력과 끝자리까지 일치*로 결정적 검증. **비가역 task는 verify로 졸업시키지 않음**(항상 사람 승인).
  > **Phase 8 구현 형태(확정):** `verify_success`는 **별도 심판 에이전트**(`memory_agent.py`의 `verify_agent`, Opus — 수행 에이전트와 분리)가 최종 화면 + 입력값 + verify 기준을 받아 *기준별 통과/실패*만 내고, harness(`main._verify_passed`)가 "≥2종 채워짐 & 채워진 종류 전부 통과 → 성공"으로 환원한다(자연어 기준을 그대로 평가, 자기선언 아님 — 분리된 심판이 실제 화면 증거를 봄). 성공률·승급/강등은 harness(`memory_store.record_outcome`)가 **결정적 코드**로 계산하고 SOP 프론트매터 `maturity`만 갱신해 **자동 git commit**한다(배운 규칙이 아니라 증거 카운터라 인젝션 방어·사람 승인 대상 아님 — 섹션 1·9). 가드레일 halt는 화면 판정 없이 실패로 집계. *최종 화면 = 마지막 관측*(성공/실패 무관)이라 마지막 액션이 실패로 끝나면 그 실패를 보고 졸업을 막는다(섹션 14-3). MVP는 `LEARNING↔ASSISTED` 한 단계, `artifact`(다운로드 파일) 판정은 후순위(채워졌으면 보수적 실패).
- 🔒 **크리티컬/비가역 스텝은 성숙도와 무관하게 항상 에스컬레이션** — 졸업 사다리와 분리.
- 사이드패널 대시보드가 레벨·성공 추세 표시 → *"신입이 크는 게" 눈에 보임.*

> **현실 기대치:** 자동화 그라운딩은 SOTA도 요소 ~49%/task ~59%로 인간보다 20–25pt 뒤처짐. **1일차 완전 자율은 약속 불가.** 초기엔 "자주 묻는" 신입사원이고 `ask_human`이 *핵심 기능*임을 팀에 설정.

---

## 11. 보안 · 규정 (법무 도메인 1순위)

| 위협 | 대응 |
|---|---|
| **API 키 유출** | LLM 키는 **백엔드에만.** 익스텐션은 누구나 압축해제 가능 → 시크릿 없음. 익스텐션은 사용자 인증 토큰만 |
| **로그인·공동인증서** | **에이전트가 직접 처리하되 안전하게** — 아래 상세 |
| **비가역 액션 (제출/결제/취하)** | 🔒 신뢰 코드 키워드 allowlist → 성숙도/확신도 무관 강제 인간 승인. **Phase 9A 구현:** `click` 도구가 라벨 검사 후 Pydantic AI `ApprovalRequired`→승인 카드→재개 시 본문 재실행(§4 메모). `always_confirm` SOP 프론트매터는 후순위 |
| **프롬프트 인젝션** | 페이지 콘텐츠 `UNTRUSTED_DATA` 격리 + 숨은 지시 제거 + 교정의 인간 승인 게이트로 SOP 세탁 차단(완전 제거는 불가) |
| **감사 추적** | 관측·제안 액션·인간 승인(시각)·실행 결과를 append-only로 기록. **MVP(Phase 9A): 평문 JSONL**(`backend/audit.py`, git 미추적, 요약만·비밀값 비기록). **SHA-256 해시체인 + WORM은 v2** |
| **PII / PIPA 국외이전** | 전송 전 로컬 리댁션, 데이터 최소화. **결정: zero-data-retention Claude 엔드포인트 + DPA(클라우드 경로) 채택. 온프렘/인-Korea는 보류.** ※ 회사 법무 최종 사인오프 필요 |
| **도메인/액션 경계** | `*.scourt.go.kr` 호스트 allowlist(주 사이트 `ecfs.scourt.go.kr`, 로그인 등 하위도메인 포함). **Phase 9A 구현:** 백엔드 `safety.domain_allowed`(신뢰 경계, env `ALLOWED_DOMAINS` 설정값화)가 `navigate`를 검사 + 익스텐션 `SCOURT_HOST` 방어심층, `session` 롤링 윈도우 레이트 리미터, 항상 보이는 **STOP**(content-script 실행기에서 클릭 직전 마지막 취소) |

### 🔐 로그인·공동인증서 — 직접 하되 안전하게

- 비밀값(ID·비번·**인증서 PIN**)은 **백엔드 금고(암호화)에 1회 등록** → 실행 때 harness가 꺼내 `fill_credential`로 직접 입력하고, **Claude는 값을 절대 못 봄**(관측·로그에서 마스킹). 비밀이 모델·SOP·평문 어디에도 안 남음.
- 인증서 *선택*(이름/기관은 비밀 아님)은 모델이, *PIN 입력*은 금고가 담당.
- 공동인증서는 **DOM(xwup)** 으로 뜬다 — 인증서 선택·PIN·확인이 모두 DOM 요소라 익스텐션이 직접 다룬다(별도 네이티브 헬퍼 앱 불필요).
- id/비밀번호 로그인은 **안티키로거 이미지 키보드**(키마다 클릭 핸들러 달린 `<img>`)를 띄워 isolated world로는 키 입력이 불가하다. 우리는 공동인증서 경로를 쓰므로 해당 없음 — 비밀번호 로그인이 필요해지면 그 키보드는 별도 설계 대상.

---

## 12. 기술 스택 · 모델 · 비용

| 레이어 | 선택 |
|---|---|
| 익스텐션 | Chrome MV3: `sidePanel` + 얇은 SW + `*.scourt.go.kr` content script(`all_frames:true`). permissions: `sidePanel, scripting, storage, debugger`(에스컬레이션 전용). host_permissions: `https://*.scourt.go.kr/*`(탭 URL 판별 + §11 도메인 allowlist) + 백엔드 `http://127.0.0.1:8000/*`(사이드패널 WS 연결) |
| 백엔드 | Python **FastAPI**, WebSocket 1개 |
| 에이전트 | **Pydantic AI 단일 Agent** (pydantic-graph 없음). `pydantic-ai-slim[anthropic]`, deferred tools |
| 관측성 | **Pydantic Logfire** (`capabilities=[Instrumentation(...)]`, OpenTelemetry — 현재 공식 권장 방식. 구 `Agent(instrument=True)`는 현 공식문서에 더는 안 나옴 → 사용 금지) |
| 감사 | SHA-256 해시체인 append-only, WORM/object-lock |

### 모델 라우팅

| 용도 | 모델 | 비고 |
|---|---|---|
| **고빈도 스텝 루프** | **`claude-sonnet-4-6`** ($3/$15, 1M ctx) — 정부 사이트 그라운딩 정확도가 병목이라 기본 권장. 비용 최우선이면 `claude-haiku-4-5`($1/$5) | adaptive thinking, effort `low`/`medium` — ⚠️ *Phase 4 발견*: Anthropic은 thinking과 output 도구(`done`)를 동시에 못 씀 → 결정적 `done` 종료를 택해 Phase 4는 thinking을 **끔**. thinking을 되살리려면 `done`을 `NativeOutput`으로 바꾸거나, 가드레일이 종료를 책임지고 일반 텍스트 종료로 전환 |
| **첫 시도·저신뢰·크리티컬·모든 교육/증류** | **`claude-opus-4-8`** ($5/$25, 1M ctx, 도구 오버헤드 290토큰, 고해상 비전 좌표 1:1) | adaptive thinking, effort `high` |

### 프롬프트 캐싱이 비용의 척추

- 안정 프리픽스 `[도구 정의] + [고정 시스템 프롬프트] + [자주 쓰는 SOP]`에 하나의 캐시 브레이크포인트. Pydantic AI에선 `AnthropicModelSettings(anthropic_cache_instructions=True, anthropic_cache_tool_definitions=True)`를 `model_settings=`로 넘겨 설정(Agent 생성자 직접 인자 아님).
- 변동 데이터(url, 요소 목록, tab_id)는 브레이크포인트 *뒤*에 주입 — 절대 캐시 프리픽스에 끼워넣지 않음.
- 캐시 읽기 ~0.1×, 쓰기 ~1.25×(5분 TTL). `result.usage.cache_read_tokens`로 검증.
- ⚠️ **캐시는 모델별로 분리됨.** Sonnet 루프 캐시와 Opus 호출 캐시는 별개 → 한 대화에서 모델을 갈아끼우지 말고 Opus 에스컬레이션은 별도 호출로(각자 자기 캐시). Opus 4.8 최소 캐시 프리픽스 4,096토큰.

### 지연시간(latency) 예산 — 대화형이라 "멈춘 듯" 보이면 안 됨

무인 배치 RPA와 달리 사람이 지켜보는 *대화형* 도구라, 절대 속도보다 **체감 끊김 없음**이 목표(진행표시가 있으면 스텝당 2~5초 수용 가능).

- **측정 먼저:** "스텝당 목표 < X초" SLO를 잡고 Logfire로 스텝을 분해(관측 생성 / WS 왕복 / 모델 추론 / 실행) → 병목이 추론인지 네트워크인지 식별.
- **추론 병목:** Sonnet+effort `low`/`medium` + 프롬프트 캐싱(읽기 0.1×는 비용뿐 아니라 TTFB↓) + **캐시 프리워밍**(세션 시작 시 `max_tokens:0`로 시스템 프롬프트 프리필) + 스트리밍으로 도구호출 조기 시작.
- **네트워크 병목:** **백엔드를 한국 리전에**(브라우저↔백엔드 왕복 단축 — 배포 모델 결정과 동시 해결) + 관측 페이로드 최소화(이미 채택: 컴팩트 인덱스, DOM텍스트>스크린샷).
- **체감 숨기기:** 사이드패널에 실시간 진행 표시(Opus 4.8은 진행 내레이션을 기본으로 잘 함) → 사용자가 "멈춘 것"으로 느끼지 않게.

---

## 13. MVP 범위 (가장 작은 1차)

> **목표: "막히면 묻고 · 가르치면 기억하고 · 교정으로 배우고 · 점점 나아진다" 4가지를 한 task로 증명.**

> **지각 기반.** 이 시스템은 "scourt 화면에서 인터랙티브 요소(버튼·입력칸)를 정확히 집어내기"에 달려 있다. scourt는 eXBuilder6/W2UI 사이트지만 핵심 컨트롤이 대부분 네이티브 태그로 렌더돼, 섹션 3의 멀티시그널 인덱스가 이를 안정적으로 포착한다(표 뼈대 같은 잡음은 키워드 좁히기·컨테이너 dedup으로 배제). MVP는 이 지각 기반 위에 바로 쌓는다.

1. **단일 task, 단일 법원** (예: `ecfs.scourt.go.kr` 사건 검색·조회). 멀티탭/팝업/iframe, CDP 신뢰입력, 결정적 리플레이, 벡터 RAG, 팀 승격, 조립식 스킬 추출은 *전부 후순위.*
2. **익스텐션:** 사이드패널(채팅 + 승인 카드 + "Show me" + STOP) + 얇은 SW 라우터 + 단일 사이트 content script(인덱스 목록 + 합성 click/type + 시연 녹화). **CDP 없음, 스크린샷 없음(텍스트만).**
3. **백엔드:** WebSocket 1개 + 단일 Pydantic AI Agent + 도구 `click/type/select/navigate/extract/ask_human/read_sop/done`. graph 없음.
4. **🟢 막히면 묻는다** — `ask_human` → 멈춤 → 사람 답 → 무상태 재개
5. **🟢 가르치면 기억한다** — "Show me" 1회 → Opus가 파라미터화 SOP 초안 → 인간 diff 승인 → git 커밋 → 다음 런에서 로드
6. **🟢 교정으로 배운다** — 다음 런에서 `ask_human` → 인간 교정 → 레슨으로 SOP 첨부(승인 후) → 그 다음엔 덜 물음
7. **🟢 점점 나아진다** — maturity + `verify_success()` + 성공률 임계 시 LEARNING→ASSISTED 1단계 승급을 대시보드에 표시
8. **🔒 안전 최소:** 크리티컬 액션 allowlist(제출 버튼)→강제 승인, 도메인 allowlist, 평문 감사 로그(해시체인은 v2), password/인증서 필드 블랭킹. **로그인은 금고+`fill_credential`로 직접**(공동인증서는 DOM이라 MVP 가능; 네이티브 `alert/confirm` 훅은 MVP에 소량 포함 — 섹션 4).

---

## 14. 위험과 한계

1. **초기 자율성** — 그라운딩 한계로 초기엔 자주 물음. 완전 자율은 후기 상태. `ask_human`은 버그가 아니라 핵심 기능.
2. **강한 모델 증류 의존** — 과/소 일반화 시 잘못된 SOP가 영속. **인간 diff 승인이 유일한 방어선** → 검토를 건너뛰면 안 됨.
3. **`verify_success` 품질** — 약하면 조용한 실패로 졸업. task별 강한 검증 기준 필요.
4. **chrome.debugger 배너** — 합성 이벤트 광범위 거부 시 상시 UX 세금. *단 scourt는 합성 이벤트를 수용함이 기존 RPA로 확인되어 위험 낮음* — 에스컬레이션은 드문 예외 경로.
5. **cross-origin iframe/OOPIF** — a11y 트리·content-script 경계를 깸. 추가 CDP flat-session 플러밍 전까지 요소를 못 봄.
6. **PIPA 국외이전** — US 엔드포인트 전송은 동의/DPA 없이는 위반 소지. *결정: zero-retention+DPA 클라우드 경로 채택(섹션 11)* — 단 회사 법무 최종 사인오프 필요.
7. **단일 에이전트 = mid-step 크래시 복구 없음** — 긴 인간 대기는 직렬화 message_history로 처리되나, 진정한 중간 크래시 복구는 후일 durable 백엔드(Temporal/DBOS) 필요(의도적 후순위).
8. **네이티브 JS 다이얼로그** — 공동인증서는 DOM으로 확인되어 네이티브 헬퍼 불필요(해소). 단 scourt가 띄우는 네이티브 `alert/confirm` 창은 content script가 못 닫음 → MAIN world 주입 훅 필요(섹션 4). Selenium이 공짜로 받던 걸 익스텐션은 명시 설계해야 함.

---

## 15. 결정이 필요한 열린 질문

### ✅ 해소됨 (검증 완료)

- **배포 모델 → 클라우드 + 안전장치로 결정.** zero-data-retention Claude 엔드포인트 + DPA + 전송 전 PII 리댁션(섹션 11). 온프렘/인-Korea 보류. (※ 회사 법무 최종 사인오프는 별도.)
- **합성 이벤트 거부 여부 → 거부 안 함.** 기존 운영 RPA가 scourt 핵심 컨트롤을 JS `.click()`·jQuery `.trigger('click')`(둘 다 `isTrusted=false`)로 매일 구동 → content script 합성 이벤트 기본 경로가 통함, `chrome.debugger`는 드문 폴백.
- **공동인증서 DOM/네이티브 → DOM.** 인증서는 DOM 목록에서 인덱스 선택(기존 RPA certIdx 패턴과 일치) → 네이티브 헬퍼 앱 불필요. (단 *다른* 네이티브 위협인 JS `alert/confirm` 다이얼로그는 섹션 4·14 참조.)

### 남은 열린 질문

1. **팀 규모/공유:** 처음부터 다수 직원이 팀 공식 SOP를 공유·승격하는 2티어가 필요한가, MVP는 1인용으로 시작?
2. ~~**`verify_success` 기준:** 타깃 task의 성공을 무엇으로 결정적 검증하나?~~ **해소(Phase 8):** 사건검색 = *결과 행 사건번호 == 입력(끝자리까지 완전일치)*를 `must_match`로, `must_appear`(접수번호 존재)·`must_not`(오류 텍스트 부재)와 함께 ≥2/4 충족. 판정은 별도 심판 에이전트가 화면 증거로(섹션 10). 다른 task는 verify 값만 채우면 됨.
3. **전자소송 사이트(`ecfs.scourt.go.kr`)에 cross-origin iframe/OOPIF가 쓰이는가?** MVP 대상 화면(사건검색·결과표·송달문서·로그인)은 same-origin이라 MVP엔 영향 없음. 다른 화면에서 OOPIF가 쓰이면 그때 CDP flat-session 포함 여부를 검토.
4. **감사 로그 보존:** 무결성(해시체인)은 전체에, 민감 페이로드는 접근통제+보존한도로 분리 저장이 충분한가, 별도 규정 요건이 있는가?
5. **도메인 범위(전용 vs 범용):** MVP는 `*.scourt.go.kr` 전용 잠금(안전·집중 — §11). 오너가 범용 활용에도 관심. → 향후 **허용 도메인 목록을 설정값으로** 분리해 범용 확장(회사용=scourt, 개인용=원하는 사이트 추가). 단 `<all_urls>` 전면 개방은 금지 — allowlist는 프롬프트 인젝션·비가역 행동 방어의 하드 레일로 **유지**(§11). 메모리 레이아웃이 이미 사이트별(`sop/<site>/`)이라 확장 친화적.

---

## 부록 A. 주요 설계 결정과 이유

| 결정 | 선택 | 이유 |
|---|---|---|
| 오케스트레이션 | **단일 `agent.run()` 루프** | 프레임워크가 graph를 "못총"이라 경고; AgentOccam +161%; 사용자의 "최소 코드" 원칙 |
| 요소 타게팅 | **harness가 만든 인덱스** | XPath는 깨지고 LLM이 잘못 생성; 인덱스는 그 오류 부류 제거(browser-use/WebVoyager 59.1% vs 30.8%) |
| 지각 채널 | **DOM 텍스트 우선** | SeeAct 텍스트 48.9% vs SoM 15.1%; 캐시되고 ~10배 저렴 |
| 크리티컬 게이트 | **신뢰 코드 allowlist** | confidence는 보정 나쁘고 인젝션으로 부풀 수 있음; 법원 문서 자동제출 방지 |
| HITL | **deferred tools** | 네트워크 횡단 목적 설계 프리미티브; 그래프 노드보다 코드 적음; durable 백엔드 불필요 |
| 학습 저장 | **NL SOP(런타임 재그라운딩)** | AWM: 경직 매크로는 첫 팝업에 깨지고 ~18.5%만 호출 |
| 자율성 | **증거 기반 스킬별 졸업** | 자율성은 선언 아닌 데이터; verify로 조용한 실패 방지(Voyager) |
| 신뢰 입력 | **기본 synthetic + 조건부 CDP** | 정부 사이트가 untrusted 거부 가능하나 CDP는 배너 세금 |
| 토큰 | **조립식 스킬 + 지연 로딩 + 캐싱** | 지금 단계만 읽고, 안정 프리픽스는 캐시 |

## 부록 B. 공식문서/연구 근거

**공식문서**
- 사이드패널: 모든 chrome API 접근, `open()`은 사용자 제스처 필요(둘 다 공식 명시). 확장 *페이지*라 SW의 30초 idle 종료 대상이 아니며 패널이 열려 있는 한 유지됨(이 지속성은 문서가 그 문구로 명시한 게 아니라 "확장 페이지" 정의에서 따라오는 추론) — [chrome.sidePanel](https://developer.chrome.com/docs/extensions/reference/api/sidePanel)
- SW는 30초 idle / 단일 요청 5분에 종료 — [SW lifecycle](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle)
- content script는 새 탭/팝업/iframe에 자동 주입 — [content scripts](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts)
- `chrome.debugger`(CDP) 사용 시 억제 불가 "디버깅 중" 배너(공식 명시). CDP `Input.dispatch*`가 `isTrusted=true` 입력을 만든다는 건 CDP 런타임 속성이지 이 문서가 보증하는 문구는 아님 — [chrome.debugger](https://developer.chrome.com/docs/extensions/reference/api/debugger)
- `captureVisibleTab`은 활성 탭 가시영역만, 2회/초 — [chrome.tabs](https://developer.chrome.com/docs/extensions/reference/api/tabs)
- deferred tools = `DeferredToolRequests`로 종료, 무상태 재개 — [Pydantic AI deferred tools](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/)
- pydantic-graph는 "못총 — 필요할 때만" — [Pydantic AI graph](https://pydantic.dev/docs/ai/graph/graph/)
- Anthropic 프롬프트 캐싱 플래그 — [Pydantic AI Anthropic](https://pydantic.dev/docs/ai/models/anthropic/)
- Claude tool-use·비전·컴퓨터유즈(DOM 에이전트엔 오버킬) — platform.claude.com

**연구**
- **AgentOccam** — 관측/행동 정리만으로 +161%(스캐폴딩 불필요)
- **SeeAct** — 텍스트 48.9% vs Set-of-Marks 15.1%
- **browser-use / WebVoyager** — 인덱스 행동 59.1% vs XPath류 30.8%
- **AWM** — 경직 매크로는 첫 팝업에 깨지고 ~18.5%만 호출 → NL 재그라운딩
- **ALLOY / ExpeL / Reflexion / Voyager** — 시연→파라미터화, ADD/EDIT/STRENGTHEN 화해, 자기검증 졸업
- **Levels-of-Autonomy** — 증거 기반 스킬별 자율 승급
