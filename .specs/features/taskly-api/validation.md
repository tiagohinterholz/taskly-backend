# Taskly API Validation

**Date**: 2026-07-24
**Spec**: `.specs/features/taskly-api/spec.md`
**Diff range**: `48b9f28..HEAD` (full feature history) — this round's actual surface: `954d17b..HEAD` (`f7b3219`, `57a7d28`, `35b7c12`, `9e79aaa`, `a913821`), i.e. the 6 post-review follow-up changes requested after prior round-2 PASS.
**Verifier**: independent sub-agent (author ≠ verifier) — fresh re-verification, no prior report content taken on faith.

**Ground rule applied**: every claim below was re-derived from fresh reads of the actual diff and current source, fresh `file:line` citations, a full gate run, and my own scratch-state mutation testing. All mutations were injected directly in the real working tree, run, then reverted via `git checkout --` (one file removed via `rm` for a temp test file that was never committed). `git status --short` was confirmed clean after every individual mutation and at the end of the session — including a stray untracked `data/attachments/` directory produced as a side effect of running the suite with the default `LOCAL_STORAGE_PATH`, which was removed to restore a clean tree.

---

## Task Completion (6 post-review follow-ups)

| # | Change | Status | Notes |
| --- | --- | --- | --- |
| 1 | `f7b3219` — auto-migration via `entrypoint.sh` | ✅ Done | `entrypoint.sh` has `set -e`, runs `alembic upgrade head`, then `exec "$@"`. A failed migration aborts the container before uvicorn ever starts (verified by reading script logic; `set -e` + no `\|\|` fallback + `exec` handoff only after the migration line — correct shell semantics, no swallowed exit code). |
| 2 | `57a7d28`+ — README, `COOKIE_SECURE` in `.env.example` | ✅ Done | `.env.example:28-32` documents `COOKIE_SECURE=false` default; matches `app/api/routers/auth.py:34` (`_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"`), unchanged production code, already tested in round 2. |
| 3 | `35b7c12` — `BaseRepository[Model]` extraction | ✅ Done | Genuinely generic (parameterized via `Generic[ModelType]` + a `model` class attribute per subclass — not hardcoded). All 5 repositories (`Project`, `Task`, `Attachment`, `User`, `RefreshToken`) inherit `__init__`/`get_by_id`/`delete` unchanged; none silently redefines them with different behavior (spot-checked all 5 files). |
| 4 | `9e79aaa` — route renesting under `/projects/{project_id}/tasks/{task_id}[/attachments/...]` | ✅ Done, IDOR protection confirmed intact (see Section 1 below) | Highest-risk change of this round — verified with 3 real mutations against the actual code, not just reading. |
| 5 | `a913821` — spec.md/tasks.md route docs updated | ✅ Done | `spec.md` ACs (TASK-01/02/03, STAT-01, ATT-01/04) now cite `/projects/{project_id}/tasks/{id}[/attachments/...]` consistently; no stale flat-route mentions remain in the spec body. |

---

## 1. IDOR / Ownership Regression Check (highest priority)

### Code path re-derived (not trusted from commit message)

`app/api/routers/tasks.py:103-114` — `_get_owned_project_id(project_id, user_id, session)`:
```python
project = await ProjectRepository(session).get_for_user(project_id, user_id)
if project is None:
    raise HTTPException(status_code=404, detail="project not found")
return project.id
```
Called as the **first line** of every nested handler body — `create_task:127`, `list_tasks:155`, `update_task:177`, `delete_task:205`, and (imported into `attachments.py`) `upload_attachment:49`, `delete_attachment:84` — **before** any task/attachment-level work. `ProjectRepository.get_for_user` (`app/repositories/project_repository.py:25-29`) filters by **both** `Project.id == project_id` **and** `Project.user_id == user_id` in one WHERE clause — genuinely ownership-scoped, not a two-step lookup-then-compare that could be reordered incorrectly.

Second layer: `TaskService.update`/`delete` (`app/services/task_service.py:94-119`) and `AttachmentService._verify_task_in_project` (`app/services/attachment_service.py:105-112`) both call `TaskRepository.get_for_project(task_id, project_id)` (`app/repositories/task_repository.py:51-55`), which filters by **both** `Task.id == task_id` **and** `Task.project_id == project_id`. A task that exists but belongs to a different project — even a project owned by the same user — resolves to `None` → `TaskNotFoundError` → 404.

**Conclusion**: the two checks are independent and composed correctly — project-URL ownership (layer 1) and task-to-project membership (layer 2). Neither can be individually bypassed without failing loudly. This is a genuine simplification (one ownership check per request instead of the old flat-route's "look up task unscoped, then resolve+check its project" chain) that does not weaken protection — it removes a step, not a check.

### Real test coverage — the "right-looking IDs" scenario

| Scenario | Test | Result |
| --- | --- | --- |
| B knows A's `project_id` and A's `task_id` (the classic full IDOR shape) | `tests/integration/api/test_tasks_router.py:227-237` (`test_update_other_users_task_returns_404`), `:291-301` (`test_delete_other_users_task_returns_404`); `test_attachments_router.py:102-113` (`test_upload_for_other_users_task_returns_404`) | ✅ 404 — caught at layer 1 (`_get_owned_project_id`), since `project_id` doesn't belong to B |
| Attacker owns `project_id` in the URL, but `task_id` belongs to a **different** project (same user, two own projects) | **No test existed in the permanent suite** — I added one (`tests/integration/api/test_verifier_scratch_idor.py`, scratch, not committed) | ✅ 404 (current code) — confirmed by my own scratch test, then deleted |
| Attacker owns `project_id`, `task_id` belongs to a victim's **different** project (cross-user + own-project-in-URL) | **No router/e2e test existed** — same scratch file | ✅ 404 (current code) — confirmed by my own scratch test, then deleted |
| The identical repository-layer scenario (task in project B, looked up via project A) | `tests/integration/repositories/test_task_repository.py:97-111` (`test_get_for_project_returns_none_for_task_in_different_project`) — **pre-existing, unit-level** | ✅ PASS — `assert found is None` |

**Finding (Minor, not a security weakness)**: the "own project in URL + foreign-project task_id" combination is proven correct at the repository-unit layer and by my own scratch e2e test, and the router's generic `TaskNotFoundError → 404` mapping is independently proven by `test_update_nonexistent_task_returns_404` / `test_delete_nonexistent_task_returns_404`. By composition the full path is safe and is defended by the permanent suite (see mutation M1 below — it **was** caught, just at the repository layer, not at the router layer). But there is no single router-level (e2e/HTTP) test that exercises this exact combined scenario end-to-end for the new nested routes. Flagged as a Minor gap with a fix task (below) — not a blocking finding.

### My own mutations (scratch state, all reverted, `git status` clean after each)

| # | File:line | Mutation | Run against | Result |
| - | --------- | -------- | ------------ | ------ |
| M1 | `app/repositories/task_repository.py:51-55` (`get_for_project`) | Removed the `Task.project_id == project_id` filter — task-to-project mismatch check silently disabled | Full suite (`uv run pytest -q`) | ✅ Killed — 1 failure: `tests/integration/repositories/test_task_repository.py::TestTaskRepositoryGetForProject::test_get_for_project_returns_none_for_task_in_different_project`. **Note**: running only the router-level files (`test_tasks_router.py` + `test_attachments_router.py`, 36 tests) showed 0 failures for this mutation — the router/e2e layer alone does not discriminate this case; only the repository-unit test does. This is the evidence behind the Minor gap above. |
| M2 | `app/api/routers/tasks.py:205` (`delete_task`) | Removed the `await _get_owned_project_id(project_id, user.id, session)` call entirely — project-ownership check bypassed | `test_tasks_router.py` + `test_auth_boundary.py` | ✅ Killed — `test_delete_other_users_task_returns_404` failed (204 instead of 404) |
| M3 | `app/repositories/project_repository.py:25-29` (`get_for_user`) | Removed the `Project.user_id == user_id` filter — project ownership check silently disabled at its root | Full suite | ✅ Killed decisively — 8 failures across both layers: `test_projects_router.py` (rename, delete), `test_tasks_router.py` (create, list, update, delete — all 4 nested task routes), and `test_project_repository.py` (unit-level). Confirms the ownership check is load-bearing everywhere it's used, including every new nested route. |

**Sensor depth**: 3 targeted mutations covering both ownership layers (project-URL ownership, task-to-project membership) plus the root repository method each depends on — proportional to this being the highest-risk change in the round, per the P0/critical-path tiering guidance.
**Result**: 3/3 killed — ✅ PASS. **No weakening of IDOR protection found.**

---

## 2. BaseRepository Correctness Check

`app/repositories/base.py:13-35`:
```python
class BaseRepository(Generic[ModelType]):
    model: type[ModelType]
    def __init__(self, session): self._session = session
    async def get_by_id(self, id): ...  # select(self.model).where(self.model.id == id)
    async def delete(self, id): ...     # delete(self.model).where(self.model.id == id); flush()
```
Genuinely generic — `self.model` is read from the subclass's class attribute, not hardcoded to any one entity.

| Repository | Inherits `get_by_id`/`delete` unchanged? | `model` set correctly? |
| --- | --- | --- |
| `ProjectRepository` | ✅ (no override) | `Project` |
| `TaskRepository` | ✅ (no override; docstring notes `get_by_id` is intentionally unscoped and currently has no caller) | `Task` |
| `AttachmentRepository` | ✅ | `Attachment` |
| `UserRepository` | ✅ | `User` |
| `RefreshTokenRepository` | ✅ (docstring explicitly notes it doesn't call `get_by_id`/`delete`, but they're still present via inheritance) | `RefreshToken` |

**Real test run (not just reading code)**: `tests/integration/repositories/test_base_repository.py` exercises `get_by_id`/`delete` via `ProjectRepository` as the vehicle, including a discriminating test (`test_get_by_id_is_unscoped_across_different_repositories_own_rows`) that looks up a `User`'s id via `ProjectRepository.get_by_id` and asserts `None` — proves the base method queries `self.model`, not a fixed table. `tests/integration/repositories/test_task_repository.py` adds an equivalent pair of tests using `TaskRepository`. Ran the full suite: **all pass** (182/182), confirming both `ProjectRepository().get_by_id(...)` and (transitively via `UserRepository(...).create(...)`) `UserRepository` work correctly through the inherited path.

**Public signature check**: grepped every `self._xxx_repository.method(...)` call across `app/services/*.py` (14 call sites) and cross-checked each against its current repository class — no signature mismatches. All `delete(id)`/`get_by_id(id)` calls use positional args, compatible with the inherited base signature.

---

## 3. Auto-Migration Check

`entrypoint.sh`:
```sh
#!/bin/sh
set -e
echo "Running database migrations (alembic upgrade head)..."
/app/.venv/bin/alembic upgrade head
echo "Migrations complete. Starting application..."
exec "$@"
```
`Dockerfile:57-58`: `ENTRYPOINT ["/app/entrypoint.sh"]` / `CMD ["/app/.venv/bin/uvicorn", ...]` — standard entrypoint+CMD composition, `$@` inside the script receives the CMD array as args.

- `set -e` means any nonzero exit from `alembic upgrade head` aborts the script before reaching `exec "$@"` — uvicorn never starts against a stale schema. No `||`, no swallowed exit code, no fallback path.
- `exec "$@"` replaces the shell process with uvicorn (correct PID-1 handling for signal forwarding in a container).

Read-only review sufficient — no doubt found, so a full `docker build`/`docker run` re-verification was not performed (per the task's own guidance that this is not required unless something looks off).

---

## 4. Spec-Anchored Re-Check of Touched ACs (new route paths only)

| Criterion (WHEN X THEN Y) | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| ISO-02: usuário tenta acessar/editar/deletar projeto/tarefa de outro | 404 | `test_tasks_router.py:73-81,100-108,227-237,291-301`; `test_attachments_router.py:102-113` — all assert `response.status_code == 404` against `/projects/{project_id}/tasks[...]` nested paths | ✅ PASS |
| ISO-01: sem sessão em qualquer endpoint de projeto/tarefa | 401 | `test_auth_boundary.py:16-39` — 10 `_PROTECTED_ROUTES` entries, all using the current nested paths (`/projects/{id}/tasks/{id}`, `.../attachments`, `.../attachments/{id}`); `:48-53` asserts exactly `== 401` | ✅ PASS — route-count cross-check: 14 route decorators total (4 auth unprotected + 10 protected) matches 10 parametrized entries 1:1 |
| TASK-01: título único campo obrigatório, `POST /projects/{id}/tasks` | 201, status inicial `not_started` | `test_tasks_router.py:38-53` | ✅ PASS |
| TASK-02: `PATCH /projects/{project_id}/tasks/{id}` atualiza qualquer campo | 200, campo persistido | `test_tasks_router.py:112-171` (title, short/full description, due_at, tags — one test per field) | ✅ PASS |
| TASK-03: `GET /projects/{id}/tasks` retorna tarefas do projeto | todas as tarefas do usuário, todos os campos | `test_tasks_router.py:85-98` | ✅ PASS |
| TASK-04: deletar tarefa remove tarefa e anexos | task row + storage files gone | `test_tasks_router.py:303-330` (`test_delete_task_removes_its_attachment_files_from_storage`) — real filesystem check via `tmp_path`, plus `:271-281` | ✅ PASS |
| STAT-01: transição livre entre os 4 estados via `PATCH /projects/{project_id}/tasks/{id}` | aceita qualquer transição, incl. "para trás" | `test_tasks_router.py:239-267` — parametrized over all 4 `TaskStatus` values + explicit `done → not_started` | ✅ PASS |
| TAG-01: salvar tags | tags persistidas | `test_tasks_router.py:162-171` | ✅ PASS |
| TAG-02: tag >20 chars → 422 nomeando a tag | corpo da resposta cita a tag | `test_tasks_router.py:173-185` — `assert too_long_tag in response.json()["detail"]` | ✅ PASS |
| ATT-01: upload via `POST /projects/{project_id}/tasks/{id}/attachments` | 201, referência do anexo | `test_attachments_router.py:38-59` | ✅ PASS |
| ATT-02: arquivo >10MB | 413, não salva | `test_attachments_router.py:81-100` — asserts 413 **and** `list(tmp_path.rglob("*")) == []` (nothing written) | ✅ PASS |
| ATT-03: `DELETE /projects/{project_id}/tasks/{id}/attachments/{attachment_id}` | apaga do storage e da listagem | `test_attachments_router.py:136-157` | ✅ PASS |

**Status**: 12/12 re-derived ACs matched spec-defined outcomes against the new route shapes. No stale-URL evidence remains — every citation above targets the current nested paths, freshly read from the current test files (not carried forward from the round-2 report, which cited the old flat `/tasks/{id}` shape for TASK-02/TASK-04 update/delete and ATT-01/03).

---

## Payload/Conjunction Rule

- `test_delete_task_removes_its_attachment_files_from_storage` — real filesystem existence checks before/after, not a mock call.
- `test_delete_task_returns_502_and_keeps_task_when_storage_fails` — status code **and** re-fetch to confirm task untouched.
- `test_update_tag_over_20_chars_returns_422` — asserts the literal offending tag string in `detail`.
- `test_upload_file_over_10mb_returns_413_without_saving` — status code **and** `tmp_path.rglob("*")` empty.
- `test_returns_401_without_session_cookie` — exact `== 401`, no looser check, one parametrized case per route.

No conjunction-rule shortfalls found in the diff surface for this round.

---

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code | ✅ — route nesting diff is mechanical (path + one param added per handler); `BaseRepository` extraction removes duplication without adding unrelated abstraction |
| Surgical changes | ✅ — no unrelated files touched beyond the stated scope |
| No scope creep | ✅ |
| Matches patterns | ✅ — `AttachmentService._verify_task_in_project` mirrors `TaskService.update/delete`'s existing `get_for_project` pattern exactly (AD-012 convention preserved, not reinvented) |
| Spec-anchored outcome check | ✅ 12/12 re-derived ACs for the new route shapes |
| Per-layer coverage | ⚠️ Minor — the specific "own project_id + foreign-project task_id" combination is covered at the repository-unit layer, not at the router/e2e layer (see Section 1 finding) |
| No unclaimed tests | ✅ |
| Documented guidelines followed | AD-011 (repositories flush-only, services commit) — re-confirmed unchanged; AD-012 (service-layer ownership checks) — re-confirmed intact through the refactor; AD-013 (route nesting rationale) — matches implementation exactly, not overstated |

---

## Edge Cases

- [x] Attacker owns `project_id`, foreign `task_id` from a different project (own or victim's) → 404 (repository-unit + my own scratch e2e test; Minor gap: no permanent router-level test)
- [x] `entrypoint.sh` migration failure aborts container start (`set -e`, read-only review)
- [x] All 6 repositories inherit generic `get_by_id`/`delete` without redefinition

---

## Gate Check

- **Gate command**: `uv sync --locked && uv run pytest -q && uv run pip-audit`
- **Result**: 182 passed, 0 failed, 0 skipped
- **pip-audit**: "No known vulnerabilities found"
- **Test count before this round** (`954d17b`): 175
- **Test count after this round** (`HEAD`): 182
- **Delta**: +7 (5 in `test_base_repository.py`, 2 in `test_task_repository.py::TestTaskRepositoryGetById`) — matches the diff exactly, no deletions or weakened assertions found

---

## Fix Plans

### Fix 1 (Minor): No router/e2e-level test for "own project_id + foreign-project task_id"

- **Root cause**: `test_tasks_router.py`/`test_attachments_router.py` test the classic cross-user IDOR shape (foreign `project_id` + foreign `task_id`) thoroughly, but not the narrower "attacker's own project in the URL, victim/foreign task_id" combination that the new nested-route topology specifically opens up. The scenario IS provably safe today (repository-unit test + generic 404-mapping test compose to cover it, confirmed live via mutation M1), but there's no single regression test pinning the combined HTTP-level behavior.
- **Fix task**: Add 1-2 tests to `test_tasks_router.py` (and optionally `test_attachments_router.py`) asserting 404 when a caller's own `project_id` is combined with a `task_id` that exists but belongs to a different project (same user's other project, and/or another user's project).
- **Priority**: Minor — not a regression, not currently exploitable; closes a coverage-layering gap surfaced by this round's route refactor.

### Fix 2 (Minor, carried forward, unchanged): Project name 1–100 char boundary untested

- Unchanged from prior rounds — still open, still out of scope, still Minor. `tests/integration/api/test_projects_router.py` has no explicit empty-name/101-char-name → 422 test.

---

## Requirement Traceability Update

| Requirement | Previous Status | New Status |
| --- | --- | --- |
| ISO-01 | ✅ Verified | ✅ Verified (re-confirmed against nested routes) |
| ISO-02 | ✅ Verified | ✅ Verified (re-confirmed; Minor router-level coverage gap noted, not a regression) |
| TASK-01..04 | ✅ Verified | ✅ Verified (re-confirmed against nested routes) |
| STAT-01 | ✅ Verified | ✅ Verified (re-confirmed) |
| TAG-01, TAG-02 | ✅ Verified | ✅ Verified (re-confirmed) |
| ATT-01..03 | ✅ Verified | ✅ Verified (re-confirmed against nested routes) |
| AUTH-01..05, PROJ-02..04 | ✅ Verified | ✅ Verified (unaffected by this round's diff, unchanged) |
| PROJ-01 (boundary) | ⚠️ Minor gap | ⚠️ Minor gap (unchanged, still open, still out of scope) |

---

## Summary

**Overall**: ✅ Ready

**Spec-anchored check**: 12/12 re-derived ACs (for routes touched by the nesting refactor) matched spec outcome precisely against the current nested paths; 0 spec-precision gaps
**Sensor**: 3/3 mutations killed, 0 survived (all mutations targeted the IDOR-critical code path: project-URL ownership, task-to-project membership, and the root repository method behind project ownership)
**Gate**: 182 passed, 0 failed, 0 skipped; `pip-audit` clean

**What works**:
1. **IDOR protection through the route refactor — confirmed intact, not weakened.** The new two-layer check (project-URL ownership via `ProjectRepository.get_for_user`, then task-to-project membership via `TaskRepository.get_for_project`) is genuinely simpler than the old flat-route chain, and genuinely still safe — proven with 3 direct mutations against the real code (not inferred from the commit message), including one (M3) that failed 8 tests across both the router and repository layers when the project-ownership filter was removed.
2. **BaseRepository is genuinely generic** — parameterized by a per-subclass `model` attribute, not hardcoded; all 5 repositories inherit unchanged, verified by a discriminating test that would fail if `get_by_id` secretly queried a fixed table.
3. **Auto-migration entrypoint is correct** — `set -e` + no swallowed exit code + `exec` handoff only after a successful migration.
4. **No repository public signature changed in a way that broke an uncovered caller** — cross-checked every `self._xxx_repository.*` call site in `app/services/*.py` against the current repository classes.

**Issues found**: One Minor coverage-layering gap (Fix 1 above) — the specific "own project + foreign-project task" IDOR sub-scenario is provably safe (unit test + generic 404-mapping test compose to cover it) but lacks a dedicated router/e2e-level regression test. Not a security regression; recommended as routine test-debt cleanup. One pre-existing Minor gap (Fix 2, project name boundary) carried forward unchanged.

**Next steps**: Ship as-is. Fix 1 and Fix 2 can be picked up together as routine test-debt cleanup; neither blocks release.
