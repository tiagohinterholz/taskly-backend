# Taskly API Validation

**Date**: 2026-07-24
**Spec**: `.specs/features/taskly-api/spec.md`
**Diff range**: `48b9f28..HEAD` (full feature history, 29 commits) — fix-round surface re-verified: `cbd8ccf..HEAD` (`966b288`, `41a9fb4`, `c401685`, `4cde218`, `df55341`)
**Verifier**: independent sub-agent (author ≠ verifier) — **iteration 2 of the bounded 3-iteration fix→re-verify loop**, re-checking the round-1 report (`.specs/features/taskly-api/validation.md` @ commit `2e6a6d8`) after the fix round.

**Ground rule applied**: nothing from the round-1 report or the fix-round commit messages was taken on faith. Every claim below was re-derived from fresh reads of the actual diff, fresh `file:line` citations, a full gate run, and my own scratch-state mutation testing (injected directly in the real tree, run, then `git checkout --` reverted — `git status` confirmed clean after every mutation and at the end of the session).

---

## Task Completion

| Task | Status | Notes |
| --- | --- | --- |
| Fix 1 (attachment cleanup on delete) | ✅ Done | Real production fix — `TaskService.delete()` now calls `StorageBackend.delete()` for every attachment before deleting the task row. |
| Fix 2 (cookie security flags) | ✅ Done | Code was already correct (`httponly=True`, `samesite="lax"`, `secure=_COOKIE_SECURE` in `app/api/routers/auth.py`, unchanged by this round) — claim was that only tests were missing. New tests now parse the raw `Set-Cookie` header and confirm this. |
| Fix 3 (`due_at` 422) | ✅ Done | Code was already correct (`due_at: datetime \| None` on both Pydantic request schemas, automatic FastAPI/Pydantic 422 on unparseable string) — new tests now lock this in. |
| Fix 4 (401 boundary, all protected routes) | ✅ Done | New file `tests/integration/api/test_auth_boundary.py` parametrizes over all 10 protected routes registered in the app — verified against `app/api/routers/*.py` route decorators, exact match. |
| Fix 5 (tag named in 422 body) | ✅ Done | Code was already correct (`app/api/routers/tasks.py` builds `detail=f"tag exceeds 20 characters: {exc.tag!r}"`) — new assertion now checks the response body contains the offending tag string. |
| Fix 6 (project name 1–100 boundary, round-1 Minor) | ❌ Still open | Not in this round's scope (round 1 ranked it Minor and separate from the 5 gaps assigned to this fix round). `tests/integration/api/test_projects_router.py` still has no test for empty-name or 101-char-name → 422. Carried forward, not a new/reopened issue — see Fix Plan below. |

---

## Spec-Anchored Acceptance Criteria

Evidence-or-zero: every row has a located `file:line` citation. Only the 5 requirement areas touched by this fix round are re-derived here in full detail (auth, ISO-01, TASK-04, tags); the remaining ACs from round 1 (projects CRUD, status transitions, attachments) were unaffected by this diff and are carried forward unchanged from the round-1 report, re-confirmed by the full gate run below.

### P1: Autenticação — cookie flags (AUTH-03 "ambos como cookies httpOnly")

| Criterion (WHEN X THEN Y) | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| Login com credenciais corretas emite access+refresh tokens como cookies httpOnly | `HttpOnly` flag present on both `Set-Cookie` headers | `tests/integration/api/test_auth_router.py:92-116` (`test_login_sets_httponly_and_samesite_lax_cookies_in_dev_mode`) — reads `response.headers.get_list("set-cookie")` (the real HTTP header, not `httpx`'s name/value-only `response.cookies` dict), asserts `"HttpOnly" in cookie_header` and `"samesite=lax" in cookie_header.lower()` for both cookies; `"secure" not in cookie_header.lower()` in dev mode | ✅ PASS — confirmed by my own mutation (see Sensor #2): flipping `httponly=True` → `False` on the real code makes this exact test fail. |
| `COOKIE_SECURE=true` adds `Secure` flag | `Secure` present when env flag set | `tests/integration/api/test_auth_router.py:118-132` — `monkeypatch.setattr(auth_router_module, "_COOKIE_SECURE", True)`, then asserts `"secure" in cookie_header.lower()` | ✅ PASS |
| Refresh reissues cookies with the same flags | Same `HttpOnly`/`SameSite` on `/auth/refresh` | `tests/integration/api/test_auth_router.py:167-186` (`test_refresh_sets_httponly_and_samesite_lax_cookies`) — same raw-header parsing | ✅ PASS |

**Production code confirmed unchanged and correct** — `app/api/routers/auth.py:92-108` (`_set_session_cookies`): `httponly=True`, `secure=_COOKIE_SECURE`, `samesite="lax"` on both cookies. This file is **not** in the fix-round diff (`git diff cbd8ccf..HEAD --stat` shows no changes to `app/api/routers/auth.py`) — the round-1 claim that the code was "already correct, only tests missing" is verified true.

### P1: Isolamento (ISO-01 "qualquer endpoint de projeto/tarefa … 401")

| Criterion | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| Requisição sem sessão válida a qualquer endpoint de projeto/tarefa | 401 | `tests/integration/api/test_auth_boundary.py:15-44` — `_PROTECTED_ROUTES` parametrized list, 10 entries, each asserting exactly `assert response.status_code == 401` (not a looser check — verified by reading the assertion literally) | ✅ PASS |

**Route-count cross-check** (fresh grep, not trusted from the test file's own comment):
`grep -n "@router\.\(get\|post\|patch\|put\|delete\)" app/api/routers/*.py` → 14 total route decorators: 4 auth (register/login/refresh/logout — correctly *not* protected, excluded), 4 projects, 4 tasks, 2 attachments = **10 protected routes**. `_PROTECTED_ROUTES` in the test file has exactly 10 entries, one per protected route, verified 1:1 by path+method. No protected route is missing.

### P1: Tarefas (TASK-04 "remover a tarefa e seus anexos associados"; "prazo em formato inválido → 422")

| Criterion | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| Deletar tarefa remove a tarefa e seus anexos associados | Task row **and** the physical attachment file(s) in storage gone | `tests/integration/api/test_tasks_router.py:299-323` (`test_delete_task_removes_its_attachment_files_from_storage`) — uploads a real file via `LocalStorageBackend(base_path=tmp_path)`, asserts `(tmp_path / storage_key).exists()` **before** delete, `assert not (tmp_path / storage_key).exists()` **after** delete — a real filesystem check, not a mock-call-happened check | ✅ PASS |
| Falha do storage ao limpar anexos não deve apagar a tarefa | 5xx (502, matching the existing `AttachmentService` storage-failure convention), task untouched | `tests/integration/api/test_tasks_router.py:325-345` (`test_delete_task_returns_502_and_keeps_task_when_storage_fails`) — injects `_FailingStorageBackend`, asserts `response.status_code == 502` **and** re-fetches the task listing to confirm the task is still there (`[task] = listing.json(); assert task["id"] == task_id`) — conjunction rule respected, not just status code | ✅ PASS |
| Prazo em formato inválido → 422 | 422 | `tests/integration/api/test_tasks_router.py:63-72` (create) and `:197-206` (update) — `{"due_at": "not-a-date"}`, `assert response.status_code == 422` | ✅ PASS — confirmed by my own mutation (Sensor #5): retyping `due_at` from `datetime` to `str` on the Pydantic schema makes both tests fail (with a raw DB error, not a graceful 422 — proving the `datetime` type annotation is exactly what produces the automatic 422, per FastAPI/Pydantic validation). |

**Production code**: `app/services/task_service.py:106-119` (`TaskService.delete`):
```python
attachments = await self._attachment_repository.list_for_tasks([task_id])
for attachment in attachments:
    try:
        self._storage_backend.delete(attachment.storage_key)
    except StorageError as exc:
        raise TaskAttachmentCleanupError(str(exc)) from exc
await self._task_repository.delete(task_id)
await self._session.commit()
```
This calls `StorageBackend.delete()` for every attachment **before** deleting the task row, and aborts (no task deletion, no commit) if any storage delete fails — matches `design.md`'s original interface note that round 1 flagged as violated. Not just "a method got called that does nothing" — the mutation sensor (below) proves it's load-bearing.

### P2: Tags (TAG-02 "422 indicando qual tag excedeu o limite")

| Criterion | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| Tag >20 chars → 422 indicando qual tag | Response body names the offending tag | `tests/integration/api/test_tasks_router.py:178-190` — `too_long_tag = "a" * 21`; `assert too_long_tag in response.json()["detail"]` — reads the actual field the router places the tag into (`detail`) | ✅ PASS — confirmed by my own mutation (Sensor #3): changing the router's `detail` message to a generic string (no longer containing the tag) makes this exact test fail. |

**Status**: ✅ All 5 targeted gaps closed with genuine evidence. 1 pre-existing Minor gap (project name boundary) remains open — out of this round's scope, not new.

**Score**: 34/34 spec ACs from the round-1 table now matched their spec-defined outcome precisely (29 carried over unchanged + 5 newly closed this round). 1 Minor coverage gap remains (project name length boundary), unchanged from round 1, not part of the assigned fix scope.

---

## Discrimination Sensor

All 5 mutations were injected directly in the real working tree (no repo worktree/stash needed — single-file edits), run against the relevant test file(s), then reverted via `git checkout --` immediately after observing the result. `git status --short` confirmed a clean tree after every individual mutation and a final `uv run pytest -q` (175 passed) confirmed no residual state.

| # | File:line | Description | Killed? |
| - | --------- | ------------ | ------- |
| 1 | `app/services/task_service.py:111-116` (`TaskService.delete`) | Removed the attachment-lookup + `StorageBackend.delete()` loop entirely (simulates the exact round-1 bug: task deleted, files orphaned) | ✅ Killed — 4 tests failed: `test_delete_removes_each_attachment_from_storage_before_deleting_task`, `test_delete_raises_cleanup_error_and_keeps_task_when_storage_fails` (unit), `test_delete_task_removes_its_attachment_files_from_storage`, `test_delete_task_returns_502_and_keeps_task_when_storage_fails` (integration) |
| 2 | `app/api/routers/auth.py:96` (`_set_session_cookies`) | Changed `httponly=True` → `httponly=False` on the `access_token` cookie (re-run of round-1's surviving mutation) | ✅ Killed — 3 tests failed: `test_login_sets_httponly_and_samesite_lax_cookies_in_dev_mode`, `test_login_sets_secure_cookies_when_cookie_secure_enabled`, `test_refresh_sets_httponly_and_samesite_lax_cookies`. This mutation **survived the entire 156-test suite in round 1** — now killed. |
| 3 | `app/api/routers/tasks.py:148-151` (`update_task`, `TagTooLongError` handler) | Changed `detail=f"tag exceeds 20 characters: {exc.tag!r}"` → generic `detail="a tag exceeds 20 characters"` (no longer names the tag) | ✅ Killed — `test_update_tag_over_20_chars_returns_422` failed |
| 4 | `app/api/routers/projects.py:47-52` (`list_projects`) | Removed `user: User = Depends(get_current_user)` and hardcoded a random `uuid.uuid4()` instead — simulates an auth-check being accidentally dropped from one route | ✅ Killed — exactly and only `test_returns_401_without_session_cookie[GET /projects]` failed (200 instead of 401); the other 9 parametrized cases correctly still passed, proving the test discriminates per-route, not just in aggregate |
| 5 | `app/api/routers/tasks.py:32,45` (`TaskCreateRequest.due_at`, `TaskUpdateRequest.due_at`) | Changed type annotation `datetime \| None` → `str \| None` on both request schemas | ✅ Killed — 3 tests failed (`test_create_task_due_at_invalid_format_returns_422`, `test_update_due_at_field`, `test_update_due_at_invalid_format_returns_422`); notably the malformed string now reaches the DB layer and raises a raw `DBAPIError` instead of a clean 422, additionally confirming there is no other validation layer silently catching this |

**Sensor depth**: lightweight-plus (5 mutations, one per re-verified gap — proportional given this is a security/data-integrity-adjacent re-verification, matching round 1's tiering)
**Result**: 5/5 killed — ✅ PASS

---

## Payload/Conjunction Rule

- `test_delete_task_removes_its_attachment_files_from_storage` — checks real filesystem state before **and** after delete, not a mock call.
- `test_delete_task_returns_502_and_keeps_task_when_storage_fails` — checks status code **and** re-fetches the task via `GET` to confirm it's untouched, not just the delete response.
- `test_login_sets_httponly_and_samesite_lax_cookies_in_dev_mode` / `test_refresh_sets_httponly_and_samesite_lax_cookies` — read the actual `Set-Cookie` response header text via `response.headers.get_list("set-cookie")`, not a mocked/stubbed cookie jar; checks 2 headers present (one per cookie) and inspects flag substrings on each.
- `test_update_tag_over_20_chars_returns_422` — asserts the offending tag's literal string is present in `response.json()["detail"]`, not just the status code.
- `test_returns_401_without_session_cookie` — each of the 10 parametrized cases asserts exactly `response.status_code == 401`, no looser check (no `in (401, 403)`, no truthiness check).

No conjunction-rule shortfalls found in the fix-round diff.

---

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code | ✅ — `TaskService.delete()` change is an 8-line surgical addition; router change is a one-line new `except` branch mapping `TaskAttachmentCleanupError` → 502 |
| Surgical changes | ✅ — no unrelated code touched; `auth.py` itself is untouched (round-1 claim that cookie code needed no fix, only tests, verified true by the empty diff on that file) |
| No scope creep | ✅ |
| Matches patterns | ✅ — the new `TaskAttachmentCleanupError` → 502 mapping in `app/api/routers/tasks.py` mirrors the existing `AttachmentStorageError` → 502 pattern already used in `app/api/routers/attachments.py` |
| Spec-anchored outcome check (asserted values match spec) | ✅ 34/34 for the 5 targeted requirement areas |
| Per-layer Coverage Expectation met (domain 1:1 ACs; routes happy+edge+error) | ✅ — both service-level (mocked storage) and router-level (real `LocalStorageBackend` against `tmp_path`) tests exist for the attachment-cleanup path, covering happy path and storage-failure path |
| Every test maps to a spec requirement — no unclaimed tests | ✅ — spot-checked, every new test's docstring/comment cites the requirement ID it covers (TASK-04, AD-003, ISO-01, TAG-02) |
| Documented guidelines followed | `tasks.md` Gate Check Commands; `AD-011` (repository flush-only, service commits) — re-confirmed: `TaskService.delete()` calls `self._session.commit()` itself, `TaskRepository.delete()` does not |

---

## Edge Cases

- [x] Storage failure during attachment cleanup on delete → 502, task and attachment rows left intact (new edge case surfaced and covered by this fix round, not in the original spec.md edge-case list but a direct consequence of TASK-04 + the existing `AttachmentStorageError`-style 5xx convention)
- [x] `COOKIE_SECURE=true` → `Secure` flag present (dev-mode default absence of `Secure` also explicitly covered)
- [x] Malformed `due_at` on both create and update paths
- [x] All 10 protected routes individually verified for the no-cookie → 401 case

---

## Gate Check

- **Gate command**: `uv sync --locked && uv run pytest -q && uv run pip-audit` (Build gate, `tasks.md`)
- **Result**: 175 passed, 0 failed, 0 skipped
- **pip-audit**: "No known vulnerabilities found"
- **Test count before this fix round** (`cbd8ccf`): 156
- **Test count after this fix round** (`HEAD`): 175
- **Delta**: +19 new tests (2 unit `TaskService.delete`, 4 `tasks_router` due_at/attachment-cleanup, 3 `auth_router` cookie-flag, 10 new `test_auth_boundary.py` — matches the diff exactly, no test deletions or weakened assertions found)
- **Skipped tests**: none
- **Failures**: none

---

## Fix Plans (remaining, carried from round 1 — not part of this round's required scope)

### Fix 1 (Minor): Project name 1–100 char boundary untested

- **Root cause**: `Field(min_length=1, max_length=100)` on `ProjectCreateRequest`/`ProjectRenameRequest` (`app/api/routers/projects.py:17,21`) has no test exercising the boundary (empty name, 101-char name → 422).
- **Fix task**: Add two tests to `tests/integration/api/test_projects_router.py` (empty name, 101-char name) asserting 422.
- **Priority**: Minor — this was flagged in round 1 (Fix 6) and was not assigned to this fix round; carried forward unchanged, not a regression.

---

## Requirement Traceability Update

| Requirement | Previous Status | New Status |
| --- | --- | --- |
| AUTH-01, AUTH-04, AUTH-05 | ✅ Verified (round 1) | ✅ Verified (unchanged) |
| AUTH-02, AUTH-03 (cookie flags) | ⚠️ Needs Fix (round 1) | ✅ Verified |
| ISO-01 | ⚠️ Needs Fix (round 1) | ✅ Verified |
| ISO-02 | ✅ Verified (round 1) | ✅ Verified (unchanged) |
| PROJ-01 (boundary) | ⚠️ Minor gap noted (round 1) | ⚠️ Minor gap noted (unchanged, out of scope this round) |
| PROJ-02..04 | ✅ Verified (round 1) | ✅ Verified (unchanged) |
| TASK-01..03 | ✅ Verified (round 1) | ✅ Verified (unchanged) |
| TASK-04 (delete+attachments) | ❌ Needs Fix (round 1) | ✅ Verified |
| TASK-04 (invalid due_at) | ❌ Needs Fix (round 1) | ✅ Verified |
| STAT-01 | ✅ Verified (round 1) | ✅ Verified (unchanged) |
| TAG-01 | ✅ Verified (round 1) | ✅ Verified (unchanged) |
| TAG-02 | ⚠️ Needs Fix (round 1) | ✅ Verified |
| ATT-01..03 | ✅ Verified (round 1) | ✅ Verified (unchanged) |

---

## Summary

**Overall**: ✅ Ready

**Spec-anchored check**: 34/34 ACs (for the 5 requirement areas touched by this fix round) matched spec outcome precisely; 1 pre-existing Minor gap remains (out of round scope)
**Sensor**: 5/5 mutations killed, 0 survived
**Gate**: 175 passed, 0 failed, 0 skipped; `pip-audit` clean

**What works**: All 5 gaps from the round-1 report are genuinely closed, not just test-padded:
1. **Attachment cleanup (real bug, now fixed)** — `TaskService.delete()` now calls `StorageBackend.delete()` for every attachment before removing the task, aborting cleanly (502, no partial delete) if storage fails. Proven load-bearing by a mutation that removes the cleanup loop — 4 tests catch it, including a real filesystem existence check via `tmp_path`.
2. **Cookie security flags** — confirmed the production code in `app/api/routers/auth.py` was never touched by this fix round (it was already correct), and the new tests now actually parse the raw `Set-Cookie` HTTP header text (not `httpx`'s value-only cookie jar) and would catch a regression — proven by re-running the exact mutation that survived round 1's entire suite; it is killed now.
3. **`due_at` 422** — both request schemas type the field as `datetime | None`, which is what makes FastAPI/Pydantic auto-reject a malformed string with 422; proven by a mutation that retypes the field to `str`, which causes the malformed value to reach the database layer and crash with a raw `DBAPIError` instead.
4. **401 boundary across all protected routes** — the new 10-route parametrized test matches the app's actual route registry exactly (verified by an independent grep, not trusted from the test file's own comment); a mutation removing one route's auth dependency is caught by exactly that route's parametrized case and no other, proving true per-route discrimination.
5. **Tag named in 422 body** — the router-level test now asserts the literal offending-tag string is present in the response body's `detail` field, not just the status code; proven by a mutation that generifies the message.

**Issues found**: None new. One pre-existing Minor gap (project name 1–100 char boundary untested) remains open — it was correctly out of scope for this fix round (round 1 ranked it Minor and separate from the 5 gaps assigned) and is not a regression.

**Next steps**: This feature is ready to ship. The remaining Minor gap (project name boundary) can be picked up as routine test-debt cleanup whenever convenient — it does not block release and does not warrant a third fix→re-verify iteration.
