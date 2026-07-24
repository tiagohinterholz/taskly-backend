# Taskly API Validation

**Date**: 2026-07-23
**Spec**: `.specs/features/taskly-api/spec.md`
**Diff range**: `48b9f28..cbd8ccf` (22 commits, T1–T18 + T18 mid-flight ownership fix)
**Verifier**: independent sub-agent (author ≠ verifier)

---

## Task Completion

| Task | Status  | Notes |
| ---- | ------- | ----- |
| T1–T18 | ✅ Done | All Done-when checkboxes in `tasks.md` show `[x]`; verified against actual code/tests, not taken on the checkbox's word. |

Note (doc-hygiene only, not a code gap): `.specs/STATE.md` Handoff still reads "Fase 7 (T17, Dockerfile) é o próximo passo" — that line was written in commit `7603b83` and T17 was committed one commit later (`cbd8ccf`). The Dockerfile itself is present, multi-stage, and non-root — the STATE.md text is simply one commit stale.

---

## Spec-Anchored Acceptance Criteria

Evidence-or-zero: every row below has a located `file:line` citation. Where the spec defines a precise outcome (status code, field value), the cited assertion targets that exact value.

### P1: Autenticação (AUTH-01..05)

| Criterion (WHEN X THEN Y) | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| Registro com e-mail único + senha ≥8 chars | 201, senha hasheada, não em plaintext | `tests/integration/api/test_auth_router.py:19-37` — `assert response.status_code == 201`; `"password" not in body`, `"password_hash" not in body` + `tests/unit/services/test_auth_service.py:67-79` — `assert call_args.args[1] != "a-plain-password"` and `PasswordHasher.verify(...) is True` | ✅ PASS |
| Registro com e-mail já cadastrado | 409, sem duplicata | `tests/integration/api/test_auth_router.py:39-51` — `assert second.status_code == 409`; `stored.id == uuid.UUID(first.json()["id"])` | ✅ PASS |
| Login com credenciais corretas | 200 + cookies httpOnly (access+refresh) | `tests/integration/api/test_auth_router.py:69-79` — `assert response.status_code == 200`; `"access_token" in response.cookies`; `"refresh_token" in response.cookies` | ⚠️ **GAP** — status/presence checked, but **no test anywhere asserts the `HttpOnly`/`Secure`/`SameSite` attributes** of the `Set-Cookie` header (`httpx`'s `response.cookies` only exposes name/value, never flags). Confirmed by discrimination sensor mutation #5 below — removing `httponly=True` survives the entire 156-test suite. |
| Login com credenciais inválidas | 401, sem revelar se e-mail existe | `tests/integration/api/test_auth_router.py:81-88` — `assert response.status_code == 401` + `tests/unit/services/test_auth_service.py:115-129` — asserts identical exception type/message for unknown-email vs. wrong-password cases | ✅ PASS |
| Refresh com token válido | novo access token sem novo login, 200 | `tests/integration/api/test_auth_router.py:92-118` — `assert response.status_code == 200`; `response.cookies["refresh_token"] != old_refresh`; decoded new access token resolves to correct user id | ✅ PASS |
| Logout | invalida/limpa cookies de sessão | `tests/integration/api/test_auth_router.py:149-168` — `assert response.status_code == 204`; cookies absent from client jar; reuse of pre-logout refresh token → 401 (proves server-side revocation, not just client-side clear) | ✅ PASS |
| >5 tentativas de login falhas/15min | 429 para novas tentativas | `tests/integration/api/test_auth_router.py:172-186` — 6 real HTTP requests through the wired app; `assert statuses[:5] == [401]*5`; `assert statuses[5] == 429` | ✅ PASS — matches the "6 real requests, not a unit-level counter" bar exactly |

### P1: Isolamento (ISO-01, ISO-02)

| Criterion | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| Endpoint de projeto/tarefa sem sessão válida | 401 | `tests/integration/api/test_projects_router.py:25-28` — `assert response.status_code == 401` (only `POST /projects`); generic dependency test `tests/integration/api/test_auth_router.py:190-204` | ⚠️ **GAP** — spec says "qualquer endpoint de projeto/tarefa" but only `POST /projects` and a synthetic ad-hoc route are directly exercised without a cookie. `GET/PATCH/DELETE /projects`, all of `/projects/{id}/tasks`, `/tasks/{id}`, and `/tasks/{id}/attachments` are never directly tested for the no-cookie case (they share `get_current_user`, so risk is structurally low, but evidence-or-zero counts it as not directly covered per route). |
| Acesso/edição/delete de projeto ou tarefa de outro usuário | 404 (nunca 403) | Project: `tests/integration/api/test_projects_router.py:73-82` (rename) and `:110-119` (delete) — both `assert response.status_code == 404`. Task: `tests/integration/api/test_tasks_router.py:47-55` (create), `:74-82` (list), `:184-194` (update), `:247-257` (delete) — all `assert response.status_code == 404` | ✅ PASS — both project and task cross-user access explicitly proven 404, not 403/401, exactly as the T18 fix (AD-012) requires. See also Discrimination Sensor mutations #1/#2 below, which confirm this is regression-protected, not just presently true. |

### P1: Projetos (PROJ-01..04)

| Criterion | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| Criar projeto (nome 1–100 chars) | 201 | `tests/integration/api/test_projects_router.py:15-23` — `assert response.status_code == 201`; `body["name"] == "Personal"` | ✅ PASS (creation). ⚠️ Boundary itself (empty name / >100 chars → 422) is enforced only via `Field(min_length=1, max_length=100)` in `app/api/routers/projects.py:18` — **no test exercises this constraint**, so the 1–100 boundary is unverified. |
| Listar projetos do usuário | apenas os próprios | `tests/integration/api/test_projects_router.py:32-52` — `test_list_projects_returns_only_own_projects` + `test_list_projects_excludes_other_users_projects` | ✅ PASS |
| Renomear projeto | atualiza nome | `tests/integration/api/test_projects_router.py:56-64` — `assert response.json()["name"] == "New name"` | ✅ PASS |
| Deletar projeto com tarefas | 409, sem deletar | `tests/integration/api/test_projects_router.py:86-97` — `assert response.status_code == 409` | ✅ PASS |
| Deletar projeto sem tarefas | 204, remove | `tests/integration/api/test_projects_router.py:99-108` — `assert response.status_code == 204`; `listing.json() == []` | ✅ PASS |

### P1: Tarefas (TASK-01..04)

| Criterion | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| Criar com só título | 201, status `not_started`, demais campos vazios/nulos | `tests/integration/api/test_tasks_router.py:22-37` — `assert body["status"] == "not_started"`; `short_description/full_description/due_at is None`; `tags == []`; `attachments == []` | ✅ PASS (conjunction rule respected — full field-value check, not just 2xx) |
| Título vazio/ausente | 422, sem criar | `tests/integration/api/test_tasks_router.py:39-45` (missing) + `tests/unit/services/test_task_service.py:71-86` (empty string, whitespace-only) | ✅ PASS |
| Atualizar qualquer campo via PATCH | persiste, retorna recurso atualizado | `tests/integration/api/test_tasks_router.py:86-155` — one test per field (title/short_description/full_description/due_at/tags), each asserting the returned value | ✅ PASS |
| Listar tarefas do projeto, todos os campos | suficiente p/ lista/kanban | `tests/integration/api/test_tasks_router.py:59-72` — checks titles set only (shallow); full-field shape is exercised on the create-response test and on `test_upload_embeds_attachment_in_task_listing` (`tests/integration/api/test_attachments_router.py:61-79`), which does assert `attachments` content on the list endpoint | ✅ PASS (with a spec-precision note — the list test itself is shallower than the create test) |
| Deletar tarefa remove tarefa **e seus anexos associados** | anexos removidos junto | `tests/integration/api/test_tasks_router.py:228-238` — `test_delete_task_removes_it_from_listing` only deletes a task **with no attachments** and checks the task disappears from listing | ❌ **NOT COVERED / functional gap** — see Fix Plan #1. `TaskService.delete()` (`app/services/task_service.py:87-92`) never calls `AttachmentService`/`StorageBackend.delete()`; it only deletes the `Task` row and relies on the DB's `ON DELETE CASCADE` FK (`app/models/attachment.py:16`) to remove `attachments` **rows**. The physical files in local/S3 storage are **never deleted** — orphaned forever. This directly contradicts `design.md`'s own component note: *"delete(user_id, task_id) -> None (remove anexos associados via `AttachmentService` antes)"*. No test creates an attachment, deletes the task, and checks the storage file is gone — because the code doesn't do it. |
| Prazo em formato inválido | 422 com mensagem de validação | — | ❌ **NOT COVERED** — no test sends a malformed `due_at` and asserts 422. Relies entirely on FastAPI/Pydantic's default datetime parsing with zero regression coverage. |

### P1: Status (STAT-01)

| Criterion | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| Transição livre entre os 4 estados, sem ordem | aceita qualquer transição | `tests/unit/services/test_task_service.py:233-255` — **all 16 (4×4) `(from_status, to_status)` combinations** via `itertools.product(TaskStatus, TaskStatus)`, parametrized; `tests/integration/api/test_tasks_router.py:196-211` — parametrized over all 4 target states at HTTP level; `tests/integration/api/test_tasks_router.py:213-224` — explicit `done → not_started` "backwards" transition, `assert backward.status_code == 200` | ✅ PASS — well beyond the happy path, exactly what the task brief asked to check |
| Status fora dos 4 permitidos | 422 | `tests/integration/api/test_tasks_router.py:167-175` — `assert response.status_code == 422` | ✅ PASS |

### P2: Tags (TAG-01, TAG-02)

| Criterion | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| Tags válidas salvas | persistidas | `tests/integration/api/test_tasks_router.py:136-145` — `assert response.json()["tags"] == ["urgent", "backend"]` | ✅ PASS |
| Tag >20 chars | 422 **indicando qual tag** excedeu | Service level: `tests/unit/services/test_task_service.py:102-111` — `assert exc_info.value.tag == too_long_tag` (names the offending tag). Router level: `tests/integration/api/test_tasks_router.py:147-155` — only `assert response.status_code == 422`, **does not assert the response body names the tag** | ⚠️ **GAP (spec-precision)** — the HTTP-facing behavior the spec actually describes ("422 indicando qual tag excedeu") is only unit-tested, not verified at the API boundary despite the router code building that exact message (`app/api/routers/tasks.py:137-141`). |

### P2: Anexos (ATT-01..03)

| Criterion | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| Upload ≤10MB | armazenado via abstração, retorna referência | `tests/integration/api/test_attachments_router.py:38-59` — asserts `filename`, `content_type`, `size_bytes`, `storage_key` present, **and** that the file bytes on disk match what was uploaded | ✅ PASS |
| Upload >10MB | 413, sem salvar | `tests/integration/api/test_attachments_router.py:81-100` — `assert response.status_code == 413`; `task["attachments"] == []`; `list(tmp_path.rglob("*")) == []` (nothing written to disk) | ✅ PASS |
| Falha do storage | 5xx, sem afetar demais dados | `tests/integration/api/test_attachments_router.py:115-132` — `assert response.status_code == 502`; task title/attachments unaffected | ✅ PASS (design.md specifies 502 precisely; test matches exactly, not just "5xx") |
| Remover anexo | apaga do storage e da lista | `tests/integration/api/test_attachments_router.py:136-157` — `assert response.status_code == 204`; `not (tmp_path / storage_key).exists()`; `task["attachments"] == []` | ✅ PASS |

### Edge Cases (spec.md)

| Edge case | `file:line` + assertion | Result |
| --- | --- | --- |
| E-mail inválido no registro → 422 | `tests/integration/api/test_auth_router.py:53-58` | ✅ PASS |
| Senha <8 chars → 422 | `tests/integration/api/test_auth_router.py:60-65` | ✅ PASS |
| Projeto/tarefa inexistente ou não pertence ao usuário → 404 | `tests/integration/api/test_projects_router.py:66-71`, `tests/integration/api/test_tasks_router.py:177-182,240-245` | ✅ PASS |
| Tarefa sem prazo → aceita nulo | `tests/integration/api/test_tasks_router.py:33` (`due_at is None`) | ✅ PASS |
| Tarefa sem tags → aceita lista vazia | `tests/integration/api/test_tasks_router.py:35` (`tags == []`) | ✅ PASS |
| Refresh token expirado/inválido → 401 | `tests/integration/api/test_auth_router.py:125-129,130-145` + `tests/unit/services/test_auth_service.py:158-166` (expiry, unit level) | ✅ PASS |

### N+1 query prevention (T13/T15 attachment batching)

| Claim | Evidence | Result |
| --- | --- | --- |
| Listing tasks with attachments batches into 1 query, not N+1 | `tests/integration/api/test_tasks_router.py:260-291` — `test_list_tasks_batches_attachment_fetch_into_a_single_call` monkeypatches `AttachmentRepository.list_for_tasks` to count invocations, asserts `call_count == 1` for 5 tasks | ✅ PASS — this is a **real regression test**, not just a manually-verified claim as STATE.md's handoff note might suggest. It would catch a future N+1 reintroduction. |

**Status**: ❌ Gaps present (5 flagged: 1 functional/untested production gap, 1 surviving security mutant, 3 test-coverage gaps)

**Score**: 29/34 spec ACs (numbered stories + edge cases) matched their spec-defined outcome precisely; 5 gaps flagged above.

---

## Discrimination Sensor

All mutations were injected directly in the real working tree, run against the relevant test file(s), then reverted via `git checkout --` immediately after observing the result. `git status`/`git diff --stat` confirmed a clean tree after each revert and after the full sequence (re-verified with a final `uv run pytest -q` → 156 passed).

| # | File:line | Description | Killed? |
| - | --------- | ------------ | ------- |
| 1 | `app/services/project_service.py:38-42` (`ProjectService.rename`) | Removed the `if owned is None: raise ProjectNotFoundError(...)` check after `get_for_user` — simulates the exact pre-T18 IDOR bug | ✅ Killed — `tests/unit/services/test_project_service.py::TestRename::test_rename_raises_not_found_when_project_not_owned_by_user` and `tests/integration/api/test_projects_router.py::TestRenameProject::test_rename_{nonexistent,other_users}_project_returns_404` all failed (200 instead of 404) |
| 2 | `app/services/task_service.py:75-78` (`TaskService.update`) | Removed the `if owned is None: raise TaskNotFoundError(...)` check after `get_for_project` — simulates the T18 task-ownership bug | ✅ Killed — `tests/unit/services/test_task_service.py::TestUpdate::test_update_raises_not_found_when_task_not_in_project` failed (`DID NOT RAISE`). Router-level `test_update_other_users_task_returns_404` still passed, because the router (`app/api/routers/tasks.py:102-112`) performs its own independent project-ownership resolution before calling the service — a defense-in-depth layer, confirmed real by this mutation, not merely claimed. |
| 3 | `app/services/task_service.py:104` (`TaskService._validate_tags`) | Changed `if len(tag) > _MAX_TAG_LENGTH` → `>=` (off-by-one at the 20-char boundary) | ✅ Killed — `tests/unit/services/test_task_service.py::TestCreate::test_create_with_valid_tags_accepted` failed (a tag of exactly 20 chars was wrongly rejected) |
| 4 | `app/services/auth_service.py:86-89` (`AuthService.authenticate`) | Removed the `PasswordHasher.verify(...)` call — any password accepted for a known email | ✅ Killed — 5 tests failed across unit + integration, including `test_login_invalid_credentials_returns_401` and the AUTH-05 rate-limit test (which depends on failed attempts actually failing) |
| 5 | `app/api/routers/auth.py:96` (`_set_session_cookies`) | Changed `httponly=True` → `httponly=False` on the `access_token` cookie | ❌ **Survived** — full suite (`uv run pytest -q`) still reported **156 passed, 0 failed**. No test inspects the raw `Set-Cookie` header or its `HttpOnly`/`Secure`/`SameSite` flags; `httpx`'s `response.cookies` mapping only exposes name/value pairs. |

**Sensor depth**: lightweight-plus (5 mutations — above the 1–3 default, given auth/ownership is the security-critical surface here)
**Result**: 4/5 killed — ❌ FAIL (1 survived)

---

## Payload/Conjunction Rule

Spot-checked across the suite — the large majority of body-asserting tests check actual field values, not just 2xx/mock-called:
- `test_create_task_with_title_only_returns_201` checks 7 distinct fields on the response body, not just status code.
- `test_upload_success_returns_attachment_reference` checks response fields **and** the actual bytes written to disk.
- `test_upload_file_over_10mb_returns_413_without_saving` checks status **and** that disk + listing are untouched.

One conjunction-rule shortfall found: `test_update_tag_over_20_chars_returns_422` (router) asserts only the status code, not that the error message names the offending tag — even though the code (`app/api/routers/tasks.py:137-141`) constructs that exact message and the spec explicitly requires it (see TAG-02 gap above).

---

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code | ✅ |
| Surgical changes | ✅ |
| No scope creep | ✅ |
| Matches patterns | ✅ — consistent layered pattern (router → service → repository) across all 4 verticals |
| Spec-anchored outcome check (asserted values match spec) | ⚠️ 29/34 — see gaps above |
| Per-layer Coverage Expectation met (domain 1:1 ACs; routes happy+edge+error) | ✅ mostly — TASK-06 (invalid due_at) and the task-delete-with-attachments case are the two Test Coverage Matrix misses |
| Every test maps to a spec requirement — no unclaimed tests | ✅ — spot-checked, no orphan/speculative tests found |
| Documented guidelines followed | `tasks.md` Test Coverage Matrix + `AD-011` (repository flush-only, service commits) — verified in `project_service.py`/`task_service.py`/`auth_service.py`/`attachment_service.py`; no repository calls `.commit()` directly (grep-confirmed) |

---

## Gate Check

- **Gate command**: `uv sync --locked && uv run pytest -q && uv run pip-audit` (Build gate, `tasks.md`)
- **Result**: 156 passed, 0 failed, 0 skipped
- **pip-audit**: "No known vulnerabilities found"
- **Test count before feature**: 0 (greenfield project — commit `48b9f28` predates any app code)
- **Test count after feature**: 156
- **Delta**: +156
- **Skipped tests**: none
- **Failures**: none

---

## Fix Plans (ranked)

### Fix 1 (Major): Task deletion orphans attachment files in storage

- **Root cause**: `TaskService.delete()` (`app/services/task_service.py:87-92`) deletes only the `Task` row; DB `ON DELETE CASCADE` (`app/models/attachment.py:16`) removes the `attachments` **rows**, but nothing ever calls `StorageBackend.delete()` for the associated files. Physical files (local disk or S3) leak forever. Contradicts `design.md`'s own stated interface for this method.
- **Fix task**: Before deleting the task, look up its attachments (`AttachmentRepository.list_for_tasks([task_id])`), delete each from `StorageBackend`, then delete the task (cascade cleans the rows). Wire through `AttachmentService`/`StorageBackend` as a dependency of `TaskService.delete`, or move the whole delete flow into a place that already has both (e.g. the router, mirroring `AttachmentService`'s error-handling pattern for storage failures).
- **Verify**: New integration test — upload an attachment to a task, delete the task, assert the file is gone from `tmp_path` (local backend).
- **Priority**: Major (real, unbounded storage leak in a feature explicitly scoped in the case; spec TASK-04 explicitly requires "remover a tarefa e seus anexos associados").

### Fix 2 (Major): No test verifies HttpOnly/Secure/SameSite on session cookies

- **Root cause**: Tests only check cookie name presence via `httpx`'s `response.cookies` dict, which doesn't expose flags. The discrimination sensor proved a regression here (removing `httponly=True`) is currently silent.
- **Fix task**: Add a test that inspects the raw `Set-Cookie` response header (e.g. `response.headers.get_list("set-cookie")`) and asserts `HttpOnly`, `SameSite=Lax`, and (when `COOKIE_SECURE=true`) `Secure` are present, for both `login` and `refresh`.
- **Verify**: Re-run discrimination mutation #5 — it should now fail.
- **Priority**: Major — this is the concrete security property AD-003 exists for ("evita exposição de token a XSS via localStorage"), currently unverified by any test.

### Fix 3 (Minor): Invalid `due_at` format never tested

- **Root cause**: No test sends a malformed `due_at` value and asserts 422.
- **Fix task**: Add `tests/integration/api/test_tasks_router.py::test_update_due_at_invalid_format_returns_422` (and/or a create-time equivalent) sending e.g. `{"due_at": "not-a-date"}`.
- **Priority**: Minor — currently protected only by FastAPI/Pydantic's default behavior, with zero regression lock-in.

### Fix 4 (Minor): ISO-01 only directly tested for one route

- **Root cause**: Only `POST /projects` (plus a synthetic ad-hoc dependency test) exercises the no-cookie → 401 path; the other project/task/attachment routes rely on it structurally via shared `get_current_user` but aren't directly asserted.
- **Fix task**: Add at least one no-cookie → 401 test per router (`GET /projects`, `GET/PATCH/DELETE` on tasks, `POST` on attachments) or a single parametrized test iterating over all protected routes.
- **Priority**: Minor — low actual risk (shared dependency), but evidence-or-zero flags it as uncovered per-route.

### Fix 5 (Minor): TAG-02 error message not asserted at the API boundary

- **Root cause**: Router-level test for tag length checks only status code; the "names the offending tag" requirement is only unit-tested.
- **Fix task**: Extend `test_update_tag_over_20_chars_returns_422` to assert the response body's `detail` contains the offending tag string.
- **Priority**: Minor.

### Fix 6 (Minor): Project name length boundary untested

- **Root cause**: `Field(min_length=1, max_length=100)` on `ProjectCreateRequest`/`ProjectRenameRequest` has no test exercising the boundary (empty name, 101-char name → 422).
- **Fix task**: Add two tests (empty name, 101-char name) asserting 422.
- **Priority**: Minor.

---

## Requirement Traceability Update

| Requirement | Previous Status | New Status |
| --- | --- | --- |
| AUTH-01, AUTH-03, AUTH-04, AUTH-05 | Implementing | ✅ Verified |
| AUTH-02 | Implementing | ⚠️ Needs Fix (cookie-flag assertion) |
| ISO-02 | Implementing | ✅ Verified |
| ISO-01 | Implementing | ⚠️ Needs Fix (per-route coverage) |
| PROJ-01..04 | Implementing | ✅ Verified (PROJ-01 boundary noted as minor gap) |
| TASK-01, TASK-02, TASK-03 | Implementing | ✅ Verified |
| TASK-04 (delete+attachments part) | Implementing | ❌ Needs Fix |
| TASK-04 (invalid due_at part) | Implementing | ❌ Needs Fix |
| STAT-01 | Implementing | ✅ Verified |
| TAG-01 | Implementing | ✅ Verified |
| TAG-02 | Implementing | ⚠️ Needs Fix (message assertion) |
| ATT-01..03 | Implementing | ✅ Verified |

---

## Summary

**Overall**: ❌ Not Ready

**Spec-anchored check**: 29/34 ACs matched spec outcome precisely; 5 gaps flagged
**Sensor**: 4/5 mutations killed, 1 survived
**Gate**: 156 passed, 0 failed, 0 skipped; `pip-audit` clean

**What works**: Auth (register/login/refresh/logout/rate-limit) is solid and precisely tested, including a real 6-request HTTP-level 429 test. The T18 ownership fix (AD-012) is empirically regression-protected — verified via two independent fault injections, one of which also surfaced an undocumented defense-in-depth layer in the task router. Status transitions (STAT-01) are exhaustively tested (all 16 from→to combinations plus an explicit backward case) at both service and HTTP layers. Attachment upload/delete/size-limit/storage-failure paths are all precisely tested including disk-level assertions. The N+1 batching fix has a real regression test (query-count assertion), not just a manual-verification claim.

**Issues found**:
1. Task deletion never cleans up attachment files in storage — real orphaned-file leak, contradicts design.md, zero test coverage (Major).
2. No test verifies the `HttpOnly`/`Secure`/`SameSite` flags on session cookies — confirmed via a surviving mutation; this is the exact property the cookie-based-auth design decision (AD-003) depends on (Major).
3. Invalid `due_at` format (422) has no test (Minor).
4. ISO-01 (401 without session) is directly tested for only 1 of ~10 protected routes (Minor).
5. TAG-02's "names the offending tag" requirement is unit-tested but not asserted at the HTTP boundary (Minor).
6. Project name 1–100 char boundary is enforced but untested (Minor).

**Next steps**: Route Fix 1 and Fix 2 back to an implementer as the priority pair (one is a real production bug, the other is an unverified security property); Fixes 3–6 can be batched into a single follow-up task. Re-run this Verifier after fixes land (iteration 1 of the bounded 3-iteration fix→re-verify loop).
