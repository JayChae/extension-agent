# TODO — 개발 진행 순서 (착수 체크리스트)

> 이 문서는 [architecture.md](architecture.md)(단일 진실 원천)를 **실제로 짤 순서**로 옮긴 것이다.
> 위에서 아래로 진행한다. **각 단계는 `검증` 기준을 통과해야 다음 단계로 넘어간다.**
> 한 번에 한 단계만. ([guidelines.md](../.claude/rules/guidelines.md) §4 — 목표·검증 기반 실행)

## 어떻게 쓰나
- `[ ]` 안 한 일 / `[x]` 끝난 일 / `[~]` 하는 중
- 각 단계 끝의 **✅ 검증**은 "이게 되면 이 단계 끝"의 객관적 기준이다. 느낌이 아니라 데이터로 판정.
- ⛔ 표시 = 이 검증에 실패하면 **다음으로 가지 말고 멈춘다**(설계를 먼저 고친다).
- 단계 옆 `(§N)` = architecture.md 해당 섹션.

---

## 📍 현재 위치
> **Phase 2 구현·자동검증 완료 — 브라우저 풀루프 확인 + 커밋은 사용자 검토 대기. 다음은 Phase 3.** "메시지 한 바퀴"(사이드패널↔백엔드 WS, 사이드패널↔SW↔content) 배관이 통했다(백엔드 echo는 일회용 WS 클라이언트로 자동검증). 다음은 "손과 눈"(§3 지각 인덱스 + §4 행동 실행기).

---

## Phase 1 — 레포 & 개발환경 세팅 (땅 고르기) (§2, §11, §12)

> 본격 코딩 전 한 번만 까는 기초. **최소한만** 깐다([guidelines.md](../.claude/rules/guidelines.md) §2) — 지금 안 쓸 도구는 나중에.
> 기본값: 백엔드 `uv`+`ruff`, 익스텐션은 번들러 없이 plain JS(MV3가 raw 파일 그대로 로드). TS/Vite는 필요해지면 그때.

- [x] 모노레포 디렉토리: `backend/` · `extension/` · `memory/` · `_docs/`(있음)
- [x] Python 환경: `uv` + `pyproject.toml`(Python 3.13), 의존성 `pydantic-ai-slim[anthropic]` · `fastapi` · `uvicorn[standard]` (`websockets`는 `uvicorn[standard]`에 포함돼 별도 추가 안 함) + 개발용 `ruff`
- [x] `.gitignore`: `.venv`, `node_modules`, `.env*`(→`!.env.example`), 빌드 산출물, **시크릿**
- [x] 시크릿 분리: `.env`(git 제외)에 `ANTHROPIC_API_KEY` — **백엔드에만, 익스텐션엔 절대 없음**(§11). `.env.example`만 커밋
- [x] 익스텐션 골격: `manifest.json`(MV3, permissions `sidePanel/scripting/storage`, 툴바클릭→패널 `action`), 빈 사이드패널 HTML, 얇은 SW, content script 등록(`*.scourt.go.kr` — 주 사이트 `ecfs.scourt.go.kr`)
- [x] (선택) 린트/포맷: 백엔드 `ruff`
- [x] `README.md`: 로컬 실행법 — 백엔드 띄우기 / 크롬에 익스텐션 "압축해제 로드"
- [x] 첫 커밋 — phase-1 PR(#2)로 머지 완료

**✅ 검증:** `uv run uvicorn ...`로 백엔드가 뜨고, 크롬 `chrome://extensions`에서 익스텐션이 (빈 사이드패널이라도) 정상 로드된다. `.env`는 git에 안 올라간다(`git status`로 확인).

---

## Phase 2 — 뼈대: 메시지가 한 바퀴 돈다 (걷기 전에 서기) (§2, §12)

> 두뇌·학습 다 빼고, **"버튼 누르면 → 백엔드 갔다 → 화면에 돌아온다"** 배관만 먼저 통한다.

- [x] WebSocket 1개 엔드포인트 (사이드패널 ↔ 백엔드 양방향) — JSON 메시지(`{type,text}`)
- [x] 얇은 SW: 툴바클릭→패널오픈, 활성 scourt 탭 해석, 라우팅만 (**추론 루프 없음**) — tabId 영구 등록(`storage.session`)은 안정 대상이 필요한 P3/4로 이연(SW idle-kill 대비)
- [x] content script(`all_frames:true`) ↔ 사이드패널 메시징 — SW가 `frameId:0` 최상위 프레임만 겨냥(응답 모호성 제거). 이미 열려 있던 탭엔 손이 없어 → SW가 `content.js` 1회 주입 후 재시도(검증 중 발견·보강, 새로고침 불필요)
- [x] 사이드패널에 채팅창 + **STOP 킬스위치** 자리 (§11) — STOP=stop 송신+입력잠금+재연결 차단(실제 "클릭 직전 취소"는 행동 실행기 생기는 P3/4)
- [x] content script ↔ 사이드패널 ↔ 백엔드 왕복 echo 한 번
- [x] (구현 중 추가) manifest `host_permissions`: `https://*.scourt.go.kr/*`(탭 URL 판별) + `http://127.0.0.1:8000/*`(WS 연결) — §11 도메인 allowlist 씨앗

**✅ 검증:** 사이드패널에서 글자 보내면 → 백엔드 거쳐 → content script가 받고 → 응답이 사이드패널에 돌아온다. (추론 루프 없음, SW에 추론 없음)

---

## Phase 3 — 손과 눈: 지각 + 행동 (§3, §4, §5)

> §3의 멀티시그널 인덱싱을 content script로 구현하고, 백엔드가 시키는 대로 실제 DOM을 조작한다.

- [ ] content script: 매 스텝 컴팩트 인덱스 요소 목록 생성 (§3 휴리스틱 — 네이티브 태그+ARIA+tabindex+onclick속성+cursor:pointer+eXBuilder6 접두사, 표뼈대 제외·컨테이너 dedup)
- [ ] 행동 실행기: `click(index)` `type(index,text)` `select(index,opt)` `navigate` `scroll` `extract` — **인덱스로만, 셀렉터 생성 금지** (§4)
- [ ] 테이블 → Markdown 변환 (행 텍스트로 매칭) (§3)
- [ ] 보안 최소: password/인증서 필드 블랭킹(전송 전), `<UNTRUSTED_PAGE_DATA>` 마커 격리 (§3)
- [ ] STOP이 클릭 직전 마지막 취소로 동작 (§11)

**✅ 검증:** 백엔드가 "인덱스 N 클릭/입력" 명령 → scourt에서 실제로 눌리고/입력되고, 새 화면의 인덱스 목록이 백엔드로 돌아온다.

---

## Phase 4 — 두뇌: 단일 에이전트 루프 (§1, §5, §6 가드레일)

> Pydantic AI `agent.run()` 하나가 관측→사고→행동을 돈다. **상태머신·그래프 없음.**
> ⚠️ 코드 짜기 전 [Pydantic AI 공식문서](https://ai.pydantic.dev/) 확인 (API 자주 바뀜, §12 / [principle.md](../.claude/rules/principle.md))

- [ ] 단일 `Agent` + 도구 연결: `click/type/select/navigate/scroll/extract/read_sop/done`
- [ ] 관측(인덱스목록+task)을 Claude에 전달 → 도구 1개 호출 → 실행 → 새 관측이 다음 입력
- [ ] 모델 라우팅: 스텝 루프 = Sonnet 4.6 (§12)
- [ ] 프롬프트 캐싱: 안정 프리픽스에 브레이크포인트 1개, 변동데이터는 뒤에 (§12)
- [ ] **안전 가드레일(코드 강제, 모델 판단 아님)**: 스텝 예산(행복경로×3) / 무진전(관측 해시 반복) / 연속 실패 K회 / 전역 타임아웃 → 걸리면 깔끔히 종료 (§6)

**✅ 검증:** "사건검색" task를 사람 개입 없이 happy path 끝까지 수행(사건번호 입력→검색→결과표 도달). 헛돌면 무한루프 대신 가드레일이 멈춘다.

---

## Phase 5 — 🟢 막히면 묻는다 (HITL) (§6)

> 확신도 if문 아님. Pydantic AI 네이티브 `deferred tools`로 구현.

- [ ] `ask_human(question, options)` → `DeferredToolRequests`로 런 종료
- [ ] 백엔드가 `all_messages()` 직렬화 저장 + 질문을 사이드패널로 푸시
- [ ] 사이드패널 질문/승인 카드 UI
- [ ] 사람 답 → `agent.run(message_history=..., deferred_tool_results=...)`로 **무상태 재개** (durable 백엔드 불필요)

**✅ 검증:** 에이전트가 모르는 지점에서 멈추고, 사람이 (분/시간 뒤) 답하면 그 자리에서 이어간다.

---

## Phase 6 — 🟢 가르치면 기억한다 ("Show me" → SOP) (§7 경로①, §9)

> 시스템을 RPA가 아니라 "신입사원"으로 만드는 핵심.

- [ ] 메모리 레이아웃: `memory/master_index.json` + `sop/scourt.go.kr/` (§9)
- [ ] 사이드패널 "Show me" 버튼 → content script가 행동마다 녹화 (역할+이름+텍스트+주변단서+입력값, **XPath 아님**) (§7)
- [ ] **Opus 4.8**이 증류 → 특정값을 `{슬롯}`으로 파라미터화, 미해결 분기는 TODO 빈칸으로 명시 (§7, §12)
- [ ] `propose_sop_diff` → 사이드패널에 diff → **사람 원클릭 승인** (= 학습 순간 + 인젝션 잠금) (§7)
- [ ] 승인 시 harness가 파일+인덱스를 같은 git commit으로 원자적 기록 (모델이 직접 안 씀) (§9)
- [ ] SOP 프론트매터: `goal / input_slots / verify / maturity(level=LEARNING)` (§9)
- [ ] 다음 런에서 `master_index.json`으로 라우팅 → `read_sop`로 지연 로딩 (§8)

**✅ 검증:** 사건검색을 "Show me"로 1회 시연 → 승인 → git 커밋 → **다음 런에서 그 SOP를 불러와** 같은 일을 한다.

---

## Phase 7 — 🟢 교정으로 배운다 (레슨 누적 + 화해) (§7 경로②③)

- [ ] 막힘/반려 시 사람 교정 → Opus가 레슨으로 증류 → 승인 후 SOP에 첨부
- [ ] **화해**: 새 레슨마다 ADD / EDIT / STRENGTHEN 중 택1 (단순 append 금지 — 모순 더미 방지) (§7)
- [ ] 반복 모순 레슨은 은퇴(recency 우선)

**✅ 검증:** 한 번 교정해준 실수(예: 사건번호 끝자리 일치)를 다음 런에서 안 묻고 스스로 지킨다.

---

## Phase 8 — 🟢 점점 나아진다 (증거 기반 졸업) (§10)

- [ ] `verify_success(criteria)` — SOP 프론트매터 구조화 `verify:`(must_appear/must_match/must_not/artifact, **4종 중 ≥2종**) 평가. **자기선언 금지** (§9, §10)
  - 사건검색 기준(지금 확정): *결과 행 사건번호 == 입력 (끝자리까지 완전일치)*
- [ ] maturity 레코드: 최근 N=10 검증된 성공률 ≥ T(0.9) → 승급 / 실패·반려 → 강등
- [ ] LEARNING → ASSISTED **1단계 승급**을 사이드패널 대시보드에 표시 (MVP는 여기까지)

**✅ 검증:** 성공이 누적되면 대시보드에서 레벨이 LEARNING→ASSISTED로 오르는 게 "눈에 보인다."

---

## 🔒 횡단 안전 (Phase 2부터 깔고, MVP 마감 전 점검) (§4, §11, §13-8)

> 안전은 마지막 단계가 아니라 처음부터 깔린다. 아래는 MVP 출시 전 반드시 켜져 있어야 할 최소선.

- [ ] **크리티컬 액션 하드 게이트**: 비가역 액션(제출 등) allowlist + `always_confirm` → 성숙도/확신도 무관 강제 승인. 실행 직전 해석된 라벨/역할이 의도와 일치하는지 검증 (§4, §11)
- [ ] **도메인 allowlist** `*.scourt.go.kr`(주 사이트 `ecfs.scourt.go.kr`) + 레이트 리미터 (§11)
- [ ] **CAPTCHA/안티봇 감지 → STOP·인간 핸드오프** (풀거나 우회 안 함) (§4)
- [ ] **로그인·공동인증서**: 비밀값은 백엔드 금고(암호화) 1회 등록 → `fill_credential(index, kind)`로 입력, **Claude는 값 못 봄**. 인증서는 DOM 확인됨(§15) (§11)
- [ ] **네이티브 `alert/confirm` 훅**: MAIN world 주입 작은 훅으로 가로채 자동수락+관측 전달 (content script 얇게 원칙의 유일한 예외) (§4)
- [ ] **평문 감사 로그**: 관측·제안 액션·인간 승인·실행 결과 기록 (해시체인은 v2) (§11, §13)

**✅ 검증:** 제출류 버튼은 성숙도와 무관하게 **항상** 승인 카드가 뜬다. 비밀값은 로그·관측 어디에도 안 남는다.

---

## 🎯 MVP 완료 정의 (§13)

> **한 task(사건검색)로 4가지가 다 증명되면 MVP 끝.**
> ① 막히면 묻고(P5) · ② 가르치면 기억하고(P6) · ③ 교정으로 배우고(P7) · ④ 점점 나아진다(P8). + 횡단 안전 최소선 켜짐.

---

## ⏭️ MVP 이후 (후순위 — 지금 짜지 않는다) (§13, §14)

- [ ] 멀티탭/팝업/iframe, cross-origin OOPIF (CDP flat-session) (§14-5)
- [ ] `chrome.debugger` 신뢰입력 에스컬레이션 (scourt는 합성이벤트 수용이라 드문 폴백) (§4, §15)
- [ ] 조립식 스킬 추출(`skills/`) + 1~2층 깊이 + DRY 공유 (§8)
- [ ] 벡터 RAG (`search_memory` — 레슨/케이스) + gotchas/cases (§9)
- [ ] 팀 2티어(개인 레슨 vs 팀 공식 SOP git PR 승격) (§9, §15-1)
- [ ] SHA-256 해시체인 + WORM 감사 (§11)
- [ ] 졸업 상위 레벨(SUPERVISED/AUTONOMOUS) + 랜덤 스팟체크 (§10)
- [ ] durable 백엔드(Temporal/DBOS) — mid-step 크래시 복구 (§14-7)
- [ ] 지연(latency) SLO 튜닝: 한국 리전 백엔드, 캐시 프리워밍, 스트리밍 (§12)
- [ ] 관측성: Pydantic Logfire(OpenTelemetry) 계측 (§12)
