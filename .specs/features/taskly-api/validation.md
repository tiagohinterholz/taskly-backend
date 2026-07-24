# Taskly API Validation

**Date**: 2026-07-24
**Spec**: `.specs/features/taskly-api/spec.md`
**Diff range**: `48b9f28..HEAD` (full feature history) — this round's actual surface: `8a75c02..db77a8b` (T19, commit `db77a8b`, "fix(attachments): add authenticated download URL to satisfy ATT-01"), preceded by `0d0e709` (task definition) and followed by `e1938ca` (handoff doc update, no code).
**Verifier**: independent sub-agent (author ≠ verifier) — fresh re-verification focused specifically on T19; no prior report content taken on faith.

**Ground rule applied**: every claim below was re-derived from fresh reads of the actual diff and current source, fresh `file:line` citations, a full gate run, and my own scratch-state mutation testing. All mutations were injected directly in the real working tree (`app/api/routers/attachments.py`), run, then reverted via `git checkout --`. `git status --short` was confirmed clean after every individual mutation and at the end of the session.

---

## Task Completion (T19)

| Task | Status | Notes |
| --- | --- | --- |
| T19 — `StorageBackend.get_url`/`.read()` (protocol + `LocalStorageBackend` + `S3StorageBackend`) | ✅ Done | `app/storage/backend.py:24-35`, `app/storage/local.py:28-36`, `app/storage/s3.py:31-45` |
| T19 — `AttachmentRepository.get_for_task` (ownership-scoped lookup) | ✅ Done | `app/repositories/attachment_repository.py:33-42` |
| T19 — `GET .../attachments/{attachment_id}/download` route | ✅ Done | `app/api/routers/attachments.py:100-128` |
| T19 — `AttachmentOut.url` always points at the download endpoint | ✅ Done | `app/api/routers/tasks.py:50-57` (field), `:74-88` (`_to_attachment_out` builder) |

---

## 1. Spec-Anchored Check for ATT-01

### (a) `url` field present in every response that embeds an attachment

| Response | Code path | `file:line` |
| --- | --- | --- |
| Upload (`POST .../attachments`) | `_to_attachment_out(attachment, project_id)` called directly | `app/api/routers/attachments.py:59` |
| Task list (`GET /projects/{id}/tasks`) | `_to_task_out` → `_to_attachment_out` per attachment | `app/api/routers/tasks.py:91-104`, called at `:181` |
| Task detail-equivalent (`PATCH /projects/{project_id}/tasks/{id}`, the only route returning a single task with its attachments post-creation) | same `_to_task_out` call | `app/api/routers/tasks.py:210` |

All three call sites route through the same `_to_attachment_out` builder (`tasks.py:74-88`) — there is exactly one place `url` is constructed, so there is no risk of the three responses diverging. **Minor observation (not a gap)**: only the upload response and the list response have a dedicated test asserting the `url` value (see below); the PATCH/update response doesn't have its own `url` assertion, but it shares the identical, already-tested code path, so this is not flagged as a coverage gap.

### (b) Test that actually follows the URL and gets real content back

| Scenario | Test | `file:line` — assertion | Result |
| --- | --- | --- | --- |
| Upload response contains the download URL, not `storage_key` | `test_upload_success_returns_attachment_reference` | `tests/integration/api/test_attachments_router.py:81-83` — `assert body["url"] == f"/projects/{project_id}/tasks/{task_id}/attachments/{body['id']}/download"` | ✅ PASS |
| Task-list response embeds the same URL per attachment | `test_upload_attachment_appears_in_task_listing` (name inferred from class; verified at cited lines) | `test_attachments_router.py:105-107` — `assert task["attachments"][0]["url"] == (...)` | ✅ PASS |
| **Local backend**: following the URL returns the real file bytes | `test_download_with_local_backend_streams_file_content` | `test_attachments_router.py:221-239` — uploads `b"hello world"`, `download_url = upload.json()["url"]`, `GET download_url`, `assert response.status_code == 200`, `assert response.content == b"hello world"`, `assert response.headers["content-type"].startswith("text/plain")` | ✅ PASS — genuinely dereferences the URL end-to-end, not a mock |
| **S3 backend (mocked client)**: following the URL 307-redirects to a presigned URL | `test_download_with_s3_backend_redirects_to_presigned_url` | `test_attachments_router.py:241-260` — swaps in `_FakeS3StorageBackend` returning a fixed presigned URL, `GET download_url`, `assert response.status_code == 307`, `assert response.headers["location"] == presigned_url` | ✅ PASS |

**Status**: ATT-01's "retornar a URL/referência do anexo" is now genuinely satisfied — `url` is present in all three response shapes and is proven dereferenceable by an end-to-end test for both storage backends (real bytes for local, real redirect target for S3). This closes the exact gap AD-016 describes (previously only `storage_key`, an internal identifier, was returned).

---

## 2. Ownership/IDOR Check on the New Download Route (highest priority)

### Code path re-derived (not trusted from commit message)

`app/api/routers/attachments.py:100-128`:
```python
@router.get("/projects/{project_id}/tasks/{task_id}/attachments/{attachment_id}/download")
async def download_attachment(...) -> Response:
    await _get_owned_project_id(project_id, user.id, session)                 # level 1: project -> user
    task = await TaskRepository(session).get_for_project(task_id, project_id)  # level 2: task -> project
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    attachment = await AttachmentRepository(session).get_for_task(attachment_id, task_id)  # level 3: attachment -> task
    if attachment is None:
        raise HTTPException(status_code=404, detail="attachment not found")

    direct_url = storage_backend.get_url(attachment.storage_key)
    if direct_url is not None:
        return RedirectResponse(direct_url, status_code=307)
    content = storage_backend.read(attachment.storage_key)
    return Response(content=content, media_type=attachment.content_type)
```
All three ownership checks execute sequentially, each raising 404 immediately on failure, **before** `storage_backend.get_url`/`.read()` is ever called — no content or redirect can be produced without passing all three. `_get_owned_project_id` (`app/api/routers/tasks.py:119-129`) and `TaskRepository.get_for_project` both filter by a compound WHERE clause (id + parent id), matching the AD-012 pattern used by every other nested route. `AttachmentRepository.get_for_task` (new in T19, `attachment_repository.py:33-42`) is the same shape.

### Real test coverage for each level

| Level | Scenario | Test | `file:line` | Result |
| --- | --- | --- | --- | --- |
| (a) project doesn't belong to user | User B requests A's full, valid `project_id/task_id/attachment_id` chain | `test_download_for_other_users_attachment_returns_404` | `test_attachments_router.py:277-295` | ✅ PASS — 404 |
| (b) task doesn't belong to that project | Caller's own `project_id`, but a `task_id` that exists under a *different* project | **No test exists for the download route** (see Finding below) | — | ❌ **GAP — confirmed by mutation, see M2** |
| (c) attachment doesn't belong to that task | Valid `project_id`+`task_id` pair (different project, same user), but `attachment_id` belongs to a different task | `test_download_for_attachment_of_a_different_task_returns_404` | `test_attachments_router.py:297-316` | ✅ PASS — 404 |
| attachment doesn't exist at all | Random `attachment_id` under an otherwise valid, owned project/task | `test_download_nonexistent_attachment_returns_404` | `test_attachments_router.py:262-275` | ✅ PASS — 404 |
| No session at all | Unauthenticated `GET` on the download route | `TestProtectedRoutesRequireSession::test_returns_401_without_session_cookie`, parametrized entry added for the download route | `test_auth_boundary.py:39-43` (route entry), `:53-58` (test, `assert response.status_code == 401`) | ✅ PASS — 401, included in the systematic `_PROTECTED_ROUTES` list alongside every other protected route |

**Finding (confirmed real, not theoretical — see mutation M2 below)**: there is no router/e2e-level test for the download route that isolates the "task belongs to a different project" case (caller's own, valid `project_id` combined with a `task_id` that exists but belongs to a different project). The existing `test_download_for_attachment_of_a_different_task_returns_404` looks similar but does **not** exercise this: in that test, `other_project_id`/`other_task_id` are a *valid, matching* pair (the task genuinely belongs to that project) — only the attachment-to-task check (level c) is what causes the 404. Level (b) is never isolated. This is the **exact same gap class as `L-007`** (already recorded as a candidate lesson from the prior verification round, where it was flagged as Minor against the `PATCH`/`DELETE` task routes and shipped anyway) — now recurring on a brand-new authenticated route.

### My own mutations (scratch state, all reverted, `git status --short` clean after each)

| # | File:line | Mutation | Run against | Result |
| - | --------- | -------- | ------------ | ------ |
| M1 | `app/api/routers/attachments.py:115` | Removed the `await _get_owned_project_id(...)` call entirely — project-ownership check (level a) bypassed | `test_attachments_router.py` + `test_auth_boundary.py` (24 tests) | ✅ **Killed** — `test_download_for_other_users_attachment_returns_404` failed (200 instead of 404) |
| M2 | `app/api/routers/attachments.py:116-118` | Removed the `task = await TaskRepository(session).get_for_project(...)` lookup and its 404 branch entirely — task-to-project check (level b) bypassed | `test_attachments_router.py` + `test_auth_boundary.py` (24 tests) | ❌ **SURVIVED — 24 passed, 0 failed.** The permanent test suite does not detect a level-(b) bypass on this route. |
| M3 | `app/api/routers/attachments.py:119` | Changed `AttachmentRepository(session).get_for_task(attachment_id, task_id)` to `AttachmentRepository(session).get_by_id(attachment_id)` — attachment-to-task check (level c) bypassed | `test_attachments_router.py` + `test_auth_boundary.py` (24 tests) | ✅ **Killed** — `test_download_for_attachment_of_a_different_task_returns_404` failed (200 instead of 404) |

**Sensor depth**: 3 targeted mutations, one per ownership level on the download route's own new code — proportional to this being a brand-new authenticated route in the feature's most historically fragile area (T18/AD-012/AD-013).
**Result**: 2/3 killed, **1 survived** — ❌ **FAIL**.

**Severity assessment**: the *deployed* code is correct — I read it directly and it performs all three checks in order, before any content is returned (confirmed above). This is not a live exploit today. But per the task's explicit rule ("Any ownership/IDOR weakness on the new route is an automatic FAIL") and the project's own discrimination-sensor discipline ("surviving mutants are fix tasks — do not mark the feature done"), a surviving mutant on exactly this axis — task-to-project ownership, on a brand-new route, in the area with the most direct history of a real IDOR bug (T18) — is treated as a blocking finding, not a cosmetic one. A future refactor that accidentally dropped the task-ownership check on this route (the same class of mistake T18 fixed elsewhere) would ship undetected.

---

## 3. Storage Abstraction Correctness

| Check | `file:line` | Evidence |
| --- | --- | --- |
| `LocalStorageBackend.get_url` always returns `None` | `app/storage/local.py:28-30` | `tests/unit/storage/test_local.py::test_get_url_always_returns_none` — real backend instance, asserts `is None` |
| `LocalStorageBackend.read` returns real bytes matching what was saved (round-trip, real file I/O) | `app/storage/local.py:32-36` | `tests/unit/storage/test_local.py::test_read_returns_the_bytes_written_by_save` — calls `backend.save(...)` then `backend.read(...)` against a real `tmp_path` filesystem, `assert content == b"hello world"` — no mocks |
| `LocalStorageBackend.read` raises `StorageError` on failure | `local.py:34-36` | `test_local.py::test_read_raises_storage_error_for_missing_key` — `pytest.raises(StorageError)` for a nonexistent key |
| `S3StorageBackend.get_url` returns a presigned URL (mocked client) | `app/storage/s3.py:31-39` | `tests/unit/storage/test_s3.py::test_get_url_returns_the_presigned_url_from_the_client` — asserts `mock_client.generate_presigned_url` called with `{"Bucket": ..., "Key": ...}` + `ExpiresIn=3600`, and the returned value matches |
| `S3StorageBackend.get_url` raises `StorageError` on failure | `s3.py:38-39` | `test_s3.py::test_get_url_raises_storage_error_when_s3_client_fails` |
| `S3StorageBackend.read` fetches via `get_object` (mocked) | `s3.py:41-45` | `test_s3.py::test_read_returns_the_object_body_bytes` — asserts `get_object` called with `Bucket`/`Key`, returned bytes match `Body.read()` |
| `S3StorageBackend.read` raises `StorageError` on failure | `s3.py:44-45` | `test_s3.py::test_read_raises_storage_error_when_s3_client_fails` |
| Error-handling pattern consistent with existing `save`/`delete` | `s3.py:16-29` vs `:31-45` | Same `try/except (BotoCoreError, ClientError): raise StorageError(...)` shape reused verbatim for `get_url`/`read` — no new error-handling pattern introduced |
| Download route branches correctly: `get_url() -> str` → 307; `get_url() -> None` → proxy via `read()` | `app/api/routers/attachments.py:123-128` | `test_download_with_local_backend_streams_file_content` (local → 200 + body) and `test_download_with_s3_backend_redirects_to_presigned_url` (S3 → 307 + `Location`) both pass against the real branching code |
| `content_type` on the proxied response comes from the DB row, not guessed/hardcoded | `attachments.py:128` — `media_type=attachment.content_type` | `test_download_with_local_backend_streams_file_content:239` — `assert response.headers["content-type"].startswith("text/plain")`, matching the `content_type` the file was uploaded with |

**Status**: ✅ All storage-abstraction checks pass with genuine evidence (real file I/O for local, mocked-but-asserted-on-call-shape for S3, consistent error handling).

---

## Payload/Conjunction Rule

- `test_upload_success_returns_attachment_reference` — asserts the exact `url` string value (not just presence), plus filename/content_type/size_bytes/storage_key.
- `test_download_with_local_backend_streams_file_content` — asserts status **and** exact body bytes **and** content-type prefix — three-way conjunction, not just "200 OK."
- `test_download_with_s3_backend_redirects_to_presigned_url` — asserts status **and** exact `Location` header value (not just "is a redirect").
- `test_get_url_returns_the_presigned_url_from_the_client` — asserts the mock was called with the exact `Params`/`ExpiresIn` payload, not just that it was called.
- `test_read_returns_the_object_body_bytes` — asserts the exact `Bucket`/`Key` payload passed to `get_object`.

No conjunction-rule shortfalls found in T19's diff surface.

---

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code | ✅ — `get_url`/`read` added only where the protocol requires them; no speculative extra methods |
| Surgical changes | ✅ — touched files are exactly the ones the diff stat shows; no unrelated refactors |
| No scope creep | ✅ |
| Matches patterns | ✅ — `get_for_task` mirrors `TaskRepository.get_for_project`'s exact shape (compound WHERE, `scalar_one_or_none`); download route reuses `_get_owned_project_id` rather than reimplementing it |
| Spec-anchored outcome check | ✅ ATT-01 now precisely matched (Section 1) |
| Per-layer coverage | ❌ Router/e2e layer missing the level-(b) case on the new route (Section 2) — same recurring gap class as `L-007` |
| No unclaimed tests | ✅ — every new test maps to ATT-01, ISO-01, ISO-02, or AD-016 |
| Documented guidelines followed | AD-016 (this fix's own decision) — implementation matches exactly what AD-016 specifies (redirect for S3, proxy for local, `url` always self-hosted); AD-012 (service/route-layer ownership checks) — followed for levels (a) and (c), **not fully defended by tests** for level (b) |

---

## Edge Cases

- [x] `AttachmentOut.url` dereferenceable for local backend (real file bytes returned)
- [x] `AttachmentOut.url` dereferenceable for S3 backend (307 + real `Location`)
- [x] Download route requires a valid session (401)
- [x] Download route 404s when project isn't owned by caller
- [ ] Download route 404s when task isn't owned by the given project — **not covered by any router/e2e test; only true by inspection + mutation-confirmed absence of a test**
- [x] Download route 404s when attachment isn't owned by the given task
- [x] Nonexistent attachment → 404

---

## Gate Check

- **Gate command**: `uv run pytest -q && uv run pip-audit`
- **Result**: 197 passed, 0 failed, 0 skipped
- **pip-audit**: "No known vulnerabilities found"
- **Test count before T19** (`8a75c02`): 182
- **Test count after T19** (`HEAD`): 197
- **Delta**: +15 — matches the diff exactly (5 attachment-repository tests, 2 local-storage tests, 4 S3-storage tests, and 5 download-route tests including the auth-boundary parametrized entry — no deletions or weakened assertions found)

---

## Discrimination Sensor

| Mutation | File:line | Description | Killed? |
| -------- | --------- | ------------ | ------- |
| M1 | `app/api/routers/attachments.py:115` | Removed project-ownership check (`_get_owned_project_id`) from the download route | ✅ Killed |
| M2 | `app/api/routers/attachments.py:116-118` | Removed task-to-project ownership check (`TaskRepository.get_for_project` + 404 branch) from the download route | ❌ **Survived** |
| M3 | `app/api/routers/attachments.py:119` | Swapped scoped `AttachmentRepository.get_for_task` for unscoped `get_by_id` | ✅ Killed |

**Sensor depth**: lightweight (3 mutations, one per ownership level), consistent with the required tiering for this feature and proportional to the download route being a brand-new authenticated endpoint on a historically fragile path.
**Result**: 2/3 killed — ❌ **FAIL**.

---

## Fix Plan

### Fix 1 (Blocking): No router/e2e-level test for "task belongs to a different project" on the download route

- **Root cause**: `TestDownloadAttachment` covers level (a) (`test_download_for_other_users_attachment_returns_404`) and level (c) (`test_download_for_attachment_of_a_different_task_returns_404`), but no test isolates level (b) — caller's own valid `project_id` combined with a `task_id` that genuinely belongs to a *different* project. This is the exact gap class already tracked as candidate lesson `L-007` (from the prior verification round, flagged against `PATCH`/`DELETE` task routes and shipped as Minor). On this brand-new route it is the difference between a killed and a surviving mutant (M2, above).
- **Fix task**: Add `test_download_for_task_in_different_project_returns_404` to `tests/integration/api/test_attachments_router.py::TestDownloadAttachment` — same user owns two projects (A, B) each with one task; attachment belongs to A's task; request `GET /projects/{A}/tasks/{B's task_id}/attachments/{attachment_id}/download` → expect 404. Mirrors the shape of `test_update_other_users_task_returns_404` but isolates the *same-user, cross-project* combination instead of the cross-user one.
- **Priority**: **Blocking** — per this round's explicit IDOR-focus rule, a surviving mutant on the ownership-check axis of a new authenticated route is treated as a FAIL, even though the deployed code is currently correct.

### Fix 2 (Minor, carried forward, unchanged): Project name 1–100 char boundary untested

- Unchanged from prior rounds — still open, still out of scope for T19, still Minor.

---

## Requirement Traceability Update

| Requirement | Previous Status | New Status |
| --- | --- | --- |
| ATT-01 | ⚠️ Gap (AD-016) — `url` not dereferenceable | ✅ Verified — `url` now genuinely dereferenceable for both storage backends, proven end-to-end |
| ISO-01 | ✅ Verified | ✅ Verified — download route added to the systematic 401 check |
| ISO-02 | ✅ Verified | ⚠️ **Gap** — levels (a) and (c) verified on the new download route; level (b) not defended by any test (surviving mutant M2) |
| All other requirements | ✅ Verified (unaffected by T19's diff) | ✅ Verified (unaffected, unchanged) |

---

## Summary

**Overall**: ❌ Not Ready — one blocking gap

**Spec-anchored check**: ATT-01 fully re-derived and matched (Section 1) — the core purpose of T19 is genuinely achieved. 0 spec-precision gaps in this round.
**Sensor**: 2/3 mutations killed, **1 survived** (M2 — task-to-project ownership check on the new download route has no discriminating router-level test)
**Gate**: 197 passed, 0 failed, 0 skipped; `pip-audit` clean

**What works**:
1. **ATT-01 is genuinely fixed.** `AttachmentOut.url` now points at a real, dereferenceable download endpoint in all three response shapes, proven by tests that actually follow the URL and get real content (local) or a real redirect target (S3), not just field-presence checks. This is exactly the gap AD-016 describes, now closed with real evidence.
2. **Storage abstraction (`get_url`/`read`) is correctly implemented and tested** for both backends, with real file I/O for local and asserted-call-shape mocks for S3, consistent error handling matching the existing `save`/`delete` pattern.
3. **Two of three ownership levels on the new download route are defended by real tests and confirmed by mutation** (M1: project ownership; M3: attachment-to-task ownership).
4. **401 boundary correctly extended** to the new route via the systematic `_PROTECTED_ROUTES` parametrized list.

**Issues found**: One blocking gap — the task-to-project ownership check (level b) on the new `GET .../attachments/{id}/download` route is implemented correctly in production code (confirmed by direct code reading) but has **no test that would catch a regression removing it** (confirmed empirically: mutation M2 removed the check and the full attachment/auth-boundary test suite still passed, 24/24). This is a recurrence of the same gap class already tracked as candidate lesson `L-007`, now on a new route.

**Next steps**: Add the fix task described in Fix 1 (one router-level test isolating the same-user, cross-project task/attachment combination for the download route), re-run the sensor to confirm M2 now kills, then re-verify. This is a small, well-scoped fix — not a redesign — and does not require touching production code, only test coverage.
