"""메모리 저장소 harness — 파일 I/O + master_index + git + 라우팅 (§9).

비모델 코드 전부 여기 모은다. 메모리 에이전트(memory_agent.py)는 SopDraft 제안만 내고,
이 모듈이 사람 승인 후 SOP 파일·인덱스를 **같은 git commit으로 원자적으로** 기록한다.
모델은 쓰기 경로에 절대 들어오지 않는다(§9 인젝션·불일치 방지).

REPO_ROOT/MEMORY_DIR은 모듈 상수로, 테스트가 임시 git repo로 덮어쓴다(agent.py MODEL 패턴).
agent.py의 read_sop는 MEMORY_DIR/sop/<path>를 읽으므로 같은 위치에 써야 다음 런에서 로드된다.
"""

import json
import subprocess
from pathlib import Path

import yaml

from memory_agent import SopDraft

REPO_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = REPO_ROOT / "memory"
INDEX_NAME = "master_index.json"


def _index_path() -> Path:
    return MEMORY_DIR / INDEX_NAME


def load_index() -> dict:
    """master_index.json 로드. 없거나 깨졌으면 빈 인덱스(손상 내성, §9 재생성 가능)."""
    path = _index_path()
    if not path.is_file():
        return {"tasks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"tasks": {}}
    data.setdefault("tasks", {})
    return data


def render_sop(draft: SopDraft, branch_notes: list[str] | None = None) -> str:
    """SopDraft → 마크다운(YAML 프론트매터 + 자연어 본문). maturity는 harness가 LEARNING으로 찍는다(§7)."""
    frontmatter = {
        "goal": draft.goal,
        "input_slots": [s.model_dump() for s in draft.input_slots],
        "verify": draft.verify.model_dump(),  # 모델 필드를 손으로 다시 적지 않음(드리프트 방지)
        "maturity": {"level": "LEARNING", "success_window": [], "autonomous_success_count": 0},
    }
    fm = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False)

    body = [f"# {draft.goal}", "", "## 순서"]
    body += [f"{i}. {step}" for i, step in enumerate(draft.steps, 1)]
    if draft.open_branches:
        body += ["", "## 미해결 분기 (처음 만나면 ask_human)"]
        body += [f"- TODO: {b}" for b in draft.open_branches]
    if branch_notes:
        body += ["", "## 레슨"]
        body += [f"- ⚠️ {note}" for note in branch_notes]
    return f"---\n{fm}---\n\n" + "\n".join(body) + "\n"


def _safe_segment(s: str) -> str:
    """경로 세그먼트 검증 — 디렉토리 탈출/구분자 차단(write 경로 가드, read_sop와 대칭)."""
    if not s or "/" in s or "\\" in s or ".." in s:
        raise ValueError(f"잘못된 이름: {s!r}")
    return s


def _git_commit(paths: list[Path], message: str) -> None:
    """해당 경로만 스테이징·커밋(pathspec 한정 — git add -A 금지). 실패 시 예외."""
    rel = [str(p.relative_to(REPO_ROOT)) for p in paths]
    subprocess.run(["git", "add", "--", *rel], cwd=REPO_ROOT, check=True, capture_output=True)
    # 내용이 동일해 스테이징된 변경이 없으면(같은 SOP 재승인) 커밋 실패 대신 조용히 통과.
    staged = subprocess.run(["git", "diff", "--cached", "--quiet", "--", *rel], cwd=REPO_ROOT)
    if staged.returncode == 0:
        return
    subprocess.run(
        ["git", "commit", "-m", message, "--", *rel], cwd=REPO_ROOT, check=True, capture_output=True
    )


def approve(
    site: str, name: str, draft: SopDraft, branch_notes: list[str] | None = None
) -> dict:
    """승인된 SOP를 파일+인덱스로 기록하고 단일 git commit으로 원자적 커밋한다.

    반환: {"file": "sop/<site>/<name>.md", "sop_path": "<site>/<name>.md"} (sop_path는 read_sop 인자)."""
    _safe_segment(site)
    _safe_segment(name)
    sop_rel = f"{site}/{name}.md"  # read_sop 인자(MEMORY_DIR/sop 기준)
    file_rel = f"sop/{sop_rel}"  # 인덱스 표기(MEMORY_DIR 기준)
    sop_file = MEMORY_DIR / "sop" / sop_rel
    sop_file.parent.mkdir(parents=True, exist_ok=True)
    sop_file.write_text(render_sop(draft, branch_notes), encoding="utf-8")

    index = load_index()
    index["tasks"][name] = {"domain": site, "file": file_rel, "goal": draft.goal}
    index_file = _index_path()
    index_file.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    _git_commit([sop_file, index_file], f"[학습] SOP 기록: {name} ({site})")
    return {"file": file_rel, "sop_path": sop_rel}


def route(task_text: str) -> str | None:
    """사용자 입력을 master_index 업무에 결정적으로 매칭 → read_sop 경로(또는 None).

    MVP 라우팅: 입력 단어(2자+)가 업무 이름/goal에 통째로 들어가면 점수. 0건이면 None(힌트 없이 진행).
    ⚠️ 약한 휴리스틱 — SOP가 여럿이면 오라우팅 가능(향후 임베딩/스키마 강화). 임베딩 없음(§9 382행)."""
    index = load_index()
    words = [w for w in task_text.split() if len(w) >= 2]
    best_file, best_score = None, 0
    for name, entry in index.get("tasks", {}).items():
        hay = name + " " + entry.get("goal", "")
        score = sum(1 for w in words if w in hay)
        if name in task_text:  # 업무 이름 직접 언급은 강한 신호
            score += 2
        if score > best_score:
            best_file, best_score = entry.get("file", ""), score
    if best_file and best_score > 0:
        return best_file[len("sop/") :] if best_file.startswith("sop/") else best_file
    return None
