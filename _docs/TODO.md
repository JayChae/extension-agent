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
> **Phase 6 구현·자동검증 완료 — 실제 scourt 시연·라이브 Opus 증류·커밋은 사용자 검토 대기. 다음은 Phase 7.** "가르치면 기억한다"가 붙었다: 사이드패널 "가르치기" 버튼 → 작은 입력창에 업무 이름 → 사람이 브라우저에서 직접 시연(+설명 추가) → content.js가 행동마다 `{kind:action, role/name/text/cue/value/url}`을 기록(XPath 아님, 비밀값 블랭킹)해 사이드패널로 즉시 송신 → 종료 시 `record_demo`로 백엔드 전송. **메모리 전담 에이전트**(`memory_agent.py`, Opus)가 행동+설명 trace를 `SopDraft`(구조화 출력)로 증류 → `propose_sop` diff를 승인 카드로 → 사람 원클릭 승인 → harness(`memory_store.py`)가 SOP 파일+`master_index.json`을 **같은 git commit으로 원자적 기록**(모델은 파일 안 씀, §9). 다음 런에서 `route()`가 결정적 라우팅 → `read_sop` 힌트 주입. 가짜 모델+임시 git repo로 자동테스트(16개 전체 통과, `backend/tests/test_learning.py` 포함).
>
> ⚠️ **Phase 6 구현 메모:** ① **수행 vs 학습 에이전트 분리**(사용자 지시) — 수행은 Sonnet 스텝 루프(`agent.py`), 학습은 **메모리 전담 Opus 에이전트**(`memory_agent.py`)가 별도로. 후자가 앞으로 모든 메모리 쓰기 *제안*의 집(Phase 7 교정→레슨 재사용). ② "가르치기"는 스텝 루프와 분리된 **harness 파이프라인**(`propose_sop_diff`를 스텝 루프 도구로 두지 않음) — 시연 중엔 도는 `agent.run()`이 없고, 모델은 쓰기 경로에 못 들어옴(§9 인젝션 방어). ③ **시연=행동+사람 설명**(사용자 지시) — 녹화 중 "설명 추가"로 의미/조건을 함께 적어 `events[]`에 시간순으로 엮음 → 모델이 조건·분기를 학습, 미해결 분기는 `open_branches`(TODO). 승인 카드에서 분기 설명을 더 적으면 레슨으로 첨부. ④ 증류는 별도 asyncio 태스크(STOP 취소·receive 루프 응답성 유지), git은 `asyncio.to_thread`. ⑤ 라우팅은 MVP 약한 휴리스틱(SOP 여럿이면 오라우팅 가능 — 향후 강화). ⑥ 신규 의존성 `pyyaml`(프론트매터 렌더). ⑦ 라이브 Opus 증류는 크레딧 사정상 `MEMORY_MODEL`/`AGENT_MODEL`로 임시 프로바이더 교체 가능.

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

- [x] content script: 매 스텝 컴팩트 인덱스 요소 목록 생성 (§3 휴리스틱 — 네이티브 태그+ARIA+tabindex+onclick속성+cursor:pointer+eXBuilder6 접두사, 표뼈대 제외·컨테이너 dedup) — 강/약 신호 분리(cursor:pointer는 상속되므로 약 신호), dedup은 "가장 안쪽 강 컨트롤 / 가장 바깥 약 요소"로 조상 walk(O(n·깊이))
- [x] 행동 실행기: `click(index)` `type(index,text)` `select(index,opt)` `navigate` `scroll` `extract` — **인덱스로만, 셀렉터 생성 금지** (§4). 합성 이벤트(레거시 RPA로 수용 확인). stale/분리 노드는 `isConnected`로 거부. ※ 사건구분은 native `<select>`가 아니라 autocomplete(`_acp_..._input`) → `type`+`click`으로 다룸(레거시 확인). ※ (실기검증 중 발견·수정) 클릭이 페이지를 이동시키면 응답 포트가 닫히는데, SW 재전송 로직이 이를 "content 없음"으로 오인해 같은 명령을 새(빈 인덱스) 화면에 재전송 → 가짜 "인덱스 없음" 에러. 에러 종류를 구분해 이동 시엔 재전송 대신 "perceive로 다시 읽으세요" 안내
- [x] 테이블 → Markdown 변환 (행 텍스트로 매칭) (§3) — 행 수 상한
- [x] 보안 최소: password/인증서 필드 블랭킹(전송 전), `<UNTRUSTED_PAGE_DATA>` 마커 격리 (§3) — **블랭킹은 구조적으로**(관측에 input `.value`를 아예 안 실음 → 불투명 id 누락 위험 없음, denylist보다 강함). 마커는 **탈출 토큰 새니타이즈**(stripMarkers)까지 Phase 3, 실제 프롬프트 펜스는 모델 입력 지점(Phase 4)에서 적용
- [x] STOP이 클릭 직전 마지막 취소로 동작 (§11) — content `stopped` 플래그를 액션 실행 직전 검사(SW 경유 `do_stop`). 하드킬(페이지 새로고침까지 유지). ⚠️ 남은 한계: STOP 시 활성 scourt 탭이 없으면 content 플래그가 안 켜지고 오류가 사이드패널에서 묵살됨(Phase 3엔 입력잠금으로 영향 적음, Phase 4 자율 루프 전 보강 대상)

**✅ 검증(달성):** 백엔드 수동 파서 명령(`click N`/`type N ...`)이 구조화 액션으로 내려가고, content 실행 후 인덱스 목록 관측이 백엔드로 돌아옴을 일회용 WS 클라이언트로 자동검증(파서 단언 + WS 왕복). 브라우저 실제 scourt 풀루프(perceive→click→type→STOP)는 사용자 검토 대기.

---

## Phase 4 — 두뇌: 단일 에이전트 루프 (§1, §5, §6 가드레일)

> Pydantic AI `agent.run()` 하나가 관측→사고→행동을 돈다. **상태머신·그래프 없음.**
> ⚠️ 코드 짜기 전 [Pydantic AI 공식문서](https://ai.pydantic.dev/) 확인 (API 자주 바뀜, §12 / [principle.md](../.claude/rules/principle.md))

- [x] 단일 `Agent` + 도구 연결: `perceive/click/type/select/navigate/scroll/extract/read_sop/done` — `done`은 일반 도구가 아니라 output 도구(`ToolOutput`)로 런을 끝냄. `read_sop`은 SOP 없으면 "없음"(Phase 6에서 채워짐). `perceive`는 설계 델타로 추가(위 마커 참조)
- [x] 관측(인덱스목록+task)을 Claude에 전달 → 도구 1개 호출 → 실행 → 새 관측이 다음 입력 — `agent.run()` **하나**가 내부 루프; 각 도구가 `Session.act()`로 WS 왕복(command 전송→obs_q에서 관측 수신). 수신루프만 ws의 유일한 reader
- [x] 모델 라우팅: 스텝 루프 = Sonnet 4.6 (§12) — `MODEL`을 `agent.run(model=...)` 시점에 주입(키 없이 import·테스트 가능). ⚠️ adaptive thinking은 done 도구와 충돌해 끔(설계 델타)
- [x] 프롬프트 캐싱: 안정 프리픽스에 브레이크포인트 1개, 변동데이터는 뒤에 (§12) — `AnthropicModelSettings(cache_instructions, cache_tool_definitions)`. 라이브 cache_read 확인은 크레딧 대기
- [x] **안전 가드레일(코드 강제, 모델 판단 아님)**: 스텝 예산(행복경로×3=24) / 무진전(관측 해시 반복 + 같은 도구·인덱스 연속) / 연속 실패 K=3 / 전역 타임아웃(180s) → `RunHalted`로 깔끔히 종료 후 사용자에게 보고 (§6)

**✅ 검증(달성):** 루프+가드레일 4종을 가짜 모델(FunctionModel)·가짜 브라우저(TestClient WS)로 자동검증 — happy path는 done 도달, 각 가드레일은 무한루프 대신 정지(8개 테스트 통과, `backend/tests/test_loop.py`). ⏳ 라이브 Sonnet happy-path + 캐시(`cache_read>0`)는 요청 형식까지 확인됨(크레딧 부족으로 보류, `backend/live_check.py`). 실제 scourt 브라우저 풀루프는 사용자 검토 대기.

---

## Phase 5 — 🟢 막히면 묻는다 (HITL) (§6)

> 확신도 if문 아님. Pydantic AI 네이티브 `deferred tools`로 구현.

- [x] `ask_human(question, options)` → `CallDeferred`로 `DeferredToolRequests`로 런 종료
- [x] 백엔드가 `all_messages()` 보관(메모리) + 질문을 사이드패널로 푸시 — 디스크 직렬화는 durable 백엔드(§14-7) 후순위
- [x] 사이드패널 질문 카드 UI(옵션 버튼 + 자유 입력, 대기 중 메인 입력 잠금) — 승인 카드 재사용 가능 형태
- [x] 사람 답(`human_answer`) → `agent.run(message_history=..., deferred_tool_results=...)`로 **무상태 재개** (durable 백엔드 불필요). 재개 시 wall-clock만 리셋·`last_tool_sig`만 비움, 작업량 카운터는 보존

**✅ 검증(달성):** 가짜 모델+가짜 브라우저로 `ask_human → 사람 답 → 그 자리에서 재개 → done`을 자동검증(10개 테스트 통과). resume()이 steps 보존·시계 리셋·last_tool_sig 클리어함도 단언. ⏳ 실제 scourt 브라우저에서 사람이 분/시간 뒤 답하는 풀루프는 사용자 검토 대기.

---

## Phase 6 — 🟢 가르치면 기억한다 ("Show me" → SOP) (§7 경로①, §9)

> 시스템을 RPA가 아니라 "신입사원"으로 만드는 핵심.

- [x] 메모리 레이아웃: `memory/master_index.json` + `sop/<site>/`(첫 승인 시 생성) (§9) — 사이트는 녹화 url에서 추론(하드코딩 아님)
- [x] 사이드패널 "가르치기" 버튼 → content script가 행동마다 녹화 (역할+이름+텍스트+주변단서+입력값, **XPath 아님**, 비밀값 블랭킹) + **설명 추가**(행동+의미를 함께) (§7)
- [x] **메모리 전담 에이전트(Opus)**가 증류 → 특정값을 `{슬롯}`으로 파라미터화, 미해결 분기는 `open_branches`(TODO 빈칸) (§7, §12)
- [x] `propose_sop`(harness 파이프라인) → 사이드패널에 diff 승인 카드 → **사람 원클릭 승인** (= 학습 순간 + 인젝션 잠금) (§7)
- [x] 승인 시 harness가 파일+인덱스를 같은 git commit으로 원자적 기록 (모델이 직접 안 씀) (§9)
- [x] SOP 프론트매터: `goal / input_slots / verify / maturity(level=LEARNING)` (§9) — yaml 렌더(`pyyaml`)
- [x] 다음 런에서 `master_index.json`으로 라우팅(`route()`) → `read_sop` 힌트 주입 (§8)

**✅ 검증(자동 달성):** 시연(`record_demo`)→증류·제안(`propose_sop`)→승인(`approve_sop`)→git 커밋(단일·해당 2경로만)→`route()` 라우팅→`read_sop` 로딩→다음 런 힌트 주입을, 가짜 모델·임시 git repo로 자동검증(16개 통과, `backend/tests/test_learning.py`). ⏳ 실제 scourt 시연 + 라이브 Opus 증류 풀루프는 사용자 검토 대기(크레딧·브라우저 필요).

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
