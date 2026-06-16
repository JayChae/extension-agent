---
name: workflow
description: Run one development Phase end-to-end with the project's standard cycle — pick the next unfinished Phase from `_docs/TODO.md`, plan it (plan mode) against `_docs/architecture.md`, implement and verify after approval, polish with `/code-review` and `/simplify`, then update `_docs/TODO.md` and `_docs/architecture.md`. Use when the user wants to take a Phase from start to finish (e.g. "do the next phase", "let's do Phase N", or invokes `/workflow`).
---

# Development Workflow — take one Phase through Plan → Implement → Review → Document

This is the project's standard development cycle. Do **one Phase at a time** (the `_docs/TODO.md` principle).
Always follow the project rules: `.claude/rules/guidelines.md` (§1 think first · §2 simplicity · §3 surgical changes · §4 goal/verification-driven) and `.claude/rules/principle.md` (official docs first).

> ⚠️ **LANGUAGE RULE — communicate with the user in Korean.**
> This skill file is written in English, but **all user-facing output MUST be in Korean**: chat replies, `AskUserQuestion` questions/options, plan content shown for approval, progress reports, and commit/PR summaries shown to the user. The user is a non-technical Korean speaker — explain in plain Korean, define jargon, keep it simple. (Code, identifiers, file contents, and commit messages stay in their natural language.)

> **Choosing the target Phase**
> - If a Phase number is given as an argument, use that Phase.
> - Otherwise read the "📍 현재 위치" marker and the checkboxes (`[ ]`/`[x]`) in `_docs/TODO.md` and pick the **next unfinished Phase**.
> - Confirm which Phase you're about to do with the user in **one short Korean line** before starting.

---

## Step 1 — Plan (plan mode)

Enter plan mode with `EnterPlanMode`, then build the implementation plan for the target Phase. (Same spirit as the originating prompt:
*"We'll do Phase x from `_docs/TODO.md`. Make a plan referencing the `_docs/architecture.md` design doc, check official docs where needed, and propose anything better than the design doc."*)

- Read that Phase's tasks and its **`✅ 검증` (verification) criteria** (the objective "this is done when…" bar) from `_docs/TODO.md`.
- Reference the relevant section (`§N`) of `_docs/architecture.md` (**single source of truth**). Don't guess — read the doc.
- **Check official docs** (`.claude/rules/principle.md`): things whose APIs change often — Pydantic AI (`ai.pydantic.dev`) · developer.chrome · FastAPI — must be verified against official docs **before coding/planning**. If the scope is broad, fan out `Explore` agents in parallel to research.
- **If you have a better proposal than the design doc**, present it with rationale and trade-offs (guidelines §1 — state assumptions, don't stay silent). If ambiguous, ask via `AskUserQuestion` (in Korean).
- Keep the plan **minimal and surgical** (§2·§3); attach a verification check to each step (§4).
- Write the plan file and get **user approval** via `ExitPlanMode`.

⛔ Do not change any code/config before approval (plan-mode rule).

### Step 1-b — Implement + verify (after approval)

- Write the code following the approved plan.
- **Actually pass that Phase's `✅ 검증` criteria** — with data, not vibes (run commands / tests / MCP / browser checks).
- Verification must pass before the next step. ⛔ If it fails, stop and **fix the plan first** (do not move on).

---

## Step 2 — `/code-review`

When implementation is done, invoke the `code-review` skill to catch **correctness bugs** in the diff.
- Dedup and verify findings; fix **only the real ones**. Skip false positives / out-of-scope / behavior-changing items **with a stated reason**.
- After fixing, **re-run** the Phase's verification.

---

## Step 3 — `/simplify`

Invoke the `simplify` skill to clean up **reuse · simplification · efficiency · altitude** (quality, not bugs).
- Apply **only behavior-preserving** cleanups. Note any skips with a reason.
- (Caution) Make sure you don't revert what `/code-review` just fixed.

---

## Step 4 — Update the docs

Bring the docs back in line with reality from this work (surgical, §3 — don't touch unrelated lines):

- **`_docs/TODO.md`**: check off finished items `[x]`, move the "📍 현재 위치" marker to the next Phase, reflect decisions that changed during implementation (e.g. dependencies / versions).
- **`_docs/architecture.md`**: reflect design deltas, resolved **open questions (§15)**, and confirmed decisions. But **keep sub-design implementation details in TODO/code** and only touch architecture for *design-level* changes.
- Update `README.md` / memory too if needed.

---

## When done

- Report what you did · verification results · what you skipped — at a glance, **in Korean**.
- **Commit/PR only after the user reviews.** No auto commit/push/PR — only when the user says to proceed.
  Work on a `phase-N` branch (never commit to main directly); confirm risky files (`.env`, `.claude/settings*.json`, build artifacts like `*.egg-info`) are excluded from staging.
