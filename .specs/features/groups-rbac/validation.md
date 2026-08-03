# Groups & RBAC Validation

**Date**: 2026-08-02
**Spec**: `.specs/features/groups-rbac/spec.md`
**Diff range**: `0f3dd85..HEAD` (full feature range — the plan commit `82c3c6e` through `2947eb1`; note this is wider than the `e292064..HEAD` range given in the task brief, because T1-T4 (`e3a2f7b`, `cab5d68`, `88d331f`, `4923bca`) landed *before* `e292064`'s AD-020/021 docs commit, not after. `e292064..HEAD` alone would have missed the security-extraction, models, and migration tasks entirely.)
**Verifier**: independent sub-agent (author ≠ verifier)

---

## Task Completion

| Task | Status  | Notes |
| ---- | ------- | ----- |
| T1   | ✅ Done | `generate_opaque_token`/`hash_token` extracted to `app/core/security.py:12-19`; `AuthService` uses them (`app/services/auth_service.py:8,116-117`). Existing `test_auth_service.py`/`test_security.py` pass unchanged (no diff). **Gap**: no new direct unit test for the extracted functions themselves (determinism/format) — see Code Quality. |
| T2   | ✅ Done | `app/models/group.py` — `GroupRole`, `Group`, `GroupMembership` (partial unique index), `GroupInvite`; registered in `app/models/__init__.py`. |
| T3   | ✅ Done | `Project.group_id` nullable FK, indexed (`app/models/project.py`). |
| T4   | ✅ Done | `alembic/versions/7c8e21a3f82b_groups_rbac.py`; `alembic upgrade head` verified clean at validation time. |
| T5   | ✅ Done | `app/repositories/group_repository.py`, all 8 interface methods, paginated where required. |
| T6   | ✅ Done | `app/repositories/group_invite_repository.py`, mirrors `RefreshTokenRepository`. |
| T7   | ✅ Done | `get_accessible_for_user`/`list_accessible_for_user` added; `get_for_user` untouched (verified by reading current file — strict method is byte-identical in intent to pre-feature behavior). |
| T8   | ✅ Done | `GroupService` lifecycle methods (`create/rename/delete/list_for_user/list_members`). |
| T9   | ✅ Done | Invite lifecycle + rate limiter. |
| T10  | ✅ Done | Membership/ownership management. |
| T11  | ✅ Done | Project link/unlink. |
| T12-T15 | ✅ Done | `app/api/routers/groups.py`, all 13+1 endpoints present with matching exception→HTTP mapping. |
| T16  | ✅ Done | `groups_router` registered in `app/main.py`; `_get_owned_project_id`→`_get_accessible_project_id` in `tasks.py`, reused by `attachments.py`; core proof test present (`TestGroupMemberTaskAccess`). |

All 16 tasks complete and committed; no partial/blocked tasks found.

---

## Spec-Anchored Acceptance Criteria

### P1: Criar grupo, convidar e colaborar

| # | Criterion (WHEN X THEN Y) | Spec-defined outcome | `file:line` + assertion | Result |
|---|---|---|---|---|
| 1 | POST `/groups` valid name (1-100) → group created, creator is Owner, 201 | 201 + Owner membership | `tests/integration/api/test_groups_router.py:48-56` — `assert response.status_code == 201`; `tests/integration/repositories/test_group_repository.py:14-26` — `assert membership.role == GroupRole.OWNER` | ✅ PASS |
| 2 | POST `/groups/{id}/invites` by Owner → unique hashed token, 7-day expiry, plaintext returned once | 201, plaintext token in body only, hashed at rest, expiry ≈ now+7d | `test_groups_router.py:302-314` — `assert "token_hash" not in body`; `tests/unit/services/test_group_service.py:265-286` — `assert create_call.args[2] != plain_token`; `test_group_service.py:288-302` — `assert before + timedelta(days=7) <= expires_at <= after + timedelta(days=7)` | ✅ PASS |
| 3 | Non-owner POST `/groups/{id}/invites` → 403, no invite created | 403, no invite row | `test_groups_router.py:326-340` — `assert response.status_code == 403`; `test_group_service.py:304-316` — `group_invite_repository.create.assert_not_awaited()` | ✅ PASS |
| 4 | Valid, unexpired token accept → Membership Member created, token consumed, 200 + group data | 200, membership role=MEMBER, consumed_at set | `test_groups_router.py:462-480` — `assert response.status_code == 200`; `assert members.json()["total"] == 2`; `test_group_service.py:353-369` — `add_member.assert_awaited_once_with(group_id, acting_user_id, GroupRole.MEMBER)` | ✅ PASS |
| 5 | Consumed token reused → 409, no duplicate membership | 409 | `test_groups_router.py:494-510` — `assert second_accept.status_code == 409`; `test_group_service.py:371-381` — `add_member.assert_not_awaited()` | ✅ PASS |
| 6 | Expired token (>7d) → 410, no membership | 410 | `test_groups_router.py:543-564` — `assert response.status_code == 410`; `test_group_service.py:383-395` | ✅ PASS — **but see Discrimination Sensor mutation 2**: the exact `expires_at == now` boundary is untested (all tests use clearly-past/clearly-future values). ⚠️ Spec-precision gap on the boundary instant. |
| 7 | Owner links own project → `group_id` set, 200 | 200, `group_id == group_id` | `test_groups_router.py:719-729` — `assert response.json()["group_id"] == group_id` | ✅ PASS |
| 8 | Link a project not owned by acting user → 403/404 | 403 or 404 (spec allows either) | `test_groups_router.py:750-767` — `assert response.status_code == 404` | ✅ PASS |
| 9 | Link a project already linked to another group → 409 | 409 | `test_groups_router.py:769-784` — `assert response.status_code == 409` | ✅ PASS |
| 10 | Member CRUDs tasks on a group-linked project → full CRUD allowed | 201/200/200/204 across create/list/update/delete | `tests/integration/api/test_tasks_router.py::TestGroupMemberTaskAccess::test_group_member_can_fully_crud_tasks_on_linked_project` — asserts 201, 200 (list total==1), 200 (update), 204 (delete) | ✅ PASS |
| 11 | Non-group-member on group-linked project's tasks → 403/404, same as v1 isolation | 404 (matches v1's existing outcome) | `test_tasks_router.py::TestGroupMemberTaskAccess::test_non_member_still_gets_404_on_group_linked_project_tasks` — asserts 404 on create/list/update/delete | ✅ PASS |
| 12 | Owner GET `/groups/{id}/members` → members with role + joined date | 200, roles + `created_at` per member | `test_groups_router.py:214-233` — `assert roles_by_user[str(owner_id)] == "owner"`; `assert all("created_at" in item ...)` | ✅ PASS |

### P2: Gestão de ciclo de vida do grupo

| # | Criterion | Spec-defined outcome | `file:line` + assertion | Result |
|---|---|---|---|---|
| 1 | DELETE `/groups/{id}/members/{user_id}` by Owner → membership removed, access revoked immediately, removed member's tasks remain | 204, member count decreases | `test_groups_router.py:568-585` — `assert response.status_code == 204`; `assert members.json()["total"] == 1` | ⚠️ **Partial**: membership removal (204 + count) is proven. "Access revoked immediately" is only proven at the `/members` listing level, not by an actual removed-member task-access attempt (no test logs the removed member back in and hits `/projects/{id}/tasks`). "Tasks the removed member created stay in the project" has **no test evidence at all** — NOT covered. |
| 2 | Member POST `/groups/{id}/leave` → own membership removed, 200 | 200 | `test_groups_router.py:619-636` — `assert response.status_code == 200`; follow-up `GET /members` returns 404 (access gone) | ✅ PASS |
| 3 | Owner leave without transfer → 409 | 409 | `test_groups_router.py:638-645` — `assert response.status_code == 409` | ✅ PASS |
| 4 | Transfer ownership → promote new, demote old, atomic | 200, roles swapped, exactly one Owner | `test_groups_router.py:692-715` — role swap confirmed via `/members`; `test_group_service.py:615-639` — call-order assertion; **empirically confirmed** by Discrimination Sensor mutation 4 (swapping the order causes a real Postgres `UniqueViolationError` on the partial index) | ✅ PASS |
| 5 | DELETE `/groups/{id}/invites/{id}` for pending invite → invalidated immediately, subsequent use returns **410** per spec | Spec text says 410 | `test_groups_router.py:414-431` — `assert accept_response.status_code == 404` | ❌ **GAP — spec/implementation mismatch**. Spec P2 AC5 literally requires 410 on subsequent use of a revoked invite. `design.md`'s Error Handling Strategy table and the actual code (`accept_invite`: `if invite is None or invite.revoked_at is not None: raise InviteNotFoundError()`) deliberately return 404 for revoked tokens — same as unknown, to avoid leaking which case it is (a reasonable, AD-012-consistent security choice, but it contradicts spec.md's literal AC as written and was never reconciled back into spec.md). |
| 6 | Owner unlinks project → `group_id` nulled, access reverts to owner only | 200, `group_id: null` | `test_groups_router.py:788-802` — `assert response.json()["group_id"] is None` | ✅ PASS |
| 7 | Delete group with linked project → 409 | 409 | `test_groups_router.py:175-188` — `assert response.status_code == 409` | ✅ PASS |
| 8 | Delete group with no linked project → group + memberships/invites cascade-deleted, 204 | 204 | `test_groups_router.py:164-173` — `assert response.status_code == 204`; listing shows empty | ⚠️ **Spec-precision gap**: cascade of `group_memberships`/`group_invites` rows is enforced structurally by the migration's `ondelete="CASCADE"` FKs (`alembic/versions/7c8e21a3f82b_groups_rbac.py:41,52`), but no test directly queries for orphaned membership/invite rows after group deletion to prove the cascade fires. |
| 9 | Rename group → 200, new name | 200 | `test_groups_router.py:129-137` — `assert response.json()["name"] == "New name"` | ✅ PASS |
| 10 | Any management action by Member → 403 for all | 403 across rename/delete/invite-create/invite-list/invite-revoke/remove-member/transfer/link/unlink | 9 separate tests, e.g. `test_groups_router.py:146,197,326,385,433,587,660,731,804` — all assert `== 403` | ✅ PASS |

### P3: Visibilidade adicional

| # | Criterion | Spec-defined outcome | `file:line` + assertion | Result |
|---|---|---|---|---|
| 1 | GET `/groups` → all groups user is Owner/Member of, with role | 200, role per group | `test_groups_router.py:72-86` (own group as owner); `tests/integration/repositories/test_group_repository.py:87-102` (both OWNER and MEMBER roles distinguished) | ✅ PASS |
| 2 | GET `/groups/{id}/invites` → only pending (not accepted/expired/revoked) | 200, filtered set | `tests/integration/repositories/test_group_invite_repository.py:63-81` — `assert [i.id for i in items] == [pending.id]` (excludes consumed/revoked/expired); router-level `test_groups_router.py:368-383` confirms the chain end-to-end | ✅ PASS |

**Status**: ⚠️ Gaps present — 1 confirmed spec/implementation mismatch (P2 AC5), 1 uncovered AC sub-claim (P2 AC1's "tasks remain"), 2 spec-precision gaps (P1 AC6 boundary, P2 AC8 cascade proof).

---

## Edge Cases

- [ ] Invite generated then group deleted before accepted → accept returns 404. **NOT covered** — no test creates an invite, deletes the group, then attempts accept. (Structurally guaranteed by `ondelete="CASCADE"` on `group_invites.group_id`, same caveat as P2 AC8.)
- [x] >10 invites in <1h → 429: `test_groups_router.py:353-364` — `assert eleventh.status_code == 429`.
- [x] Already-member accepts a new invite for the same group → 409: `test_groups_router.py:512-541` — `assert response.status_code == 409`.
- [ ] Group-linked project deleted (v1 `DELETE /projects/{id}` flow, blocked if it has tasks) — same rule applies regardless of `group_id`. **NOT explicitly retested** with a group-linked project; only the pre-existing v1 test covers the base rule, and the code path (`ProjectService.delete`) never references `group_id`, so risk is low but the combined case is unproven.
- [x] Group name <1 or >100 chars → 422: over-100 covered (`test_groups_router.py:63-68`, `assert response.status_code == 422`). **Empty-string (0 chars) is NOT explicitly tested** — relies on `Field(min_length=1, max_length=100)` declaratively, same unverified pattern as the pre-existing `ProjectCreateRequest`.
- [x] Transfer ownership to a non-member → 404/422: `test_groups_router.py:681-690` — `assert response.status_code == 404`.

---

## Discrimination Sensor

All mutations applied directly to the real working tree (no worktree/stash available for a quick single-repo check; each mutation was verified reverted via `git checkout` + content re-read before the next one, and `git status` confirmed clean throughout).

| # | File:line | Description | Killed? |
|---|---|---|---|
| 1 | `app/repositories/project_repository.py:24-27` (`_accessible_condition`) | Removed the group-membership OR-branch entirely (isolates "does group-member access actually depend on this branch") | ✅ Killed — 4 tests failed: `test_list_accessible_for_user_includes_group_accessible_projects`, `test_get_accessible_for_user_returns_project_for_group_member`, and both `TestGroupMemberTaskAccess` tests |
| 2 | `app/services/group_service.py:168` (`accept_invite`) | `invite.expires_at < now` → `invite.expires_at <= now` (off-by-one at the exact expiry instant) | ❌ **Survived** — 94/94 passed unchanged. No test uses an invite whose `expires_at` equals "now" exactly; all expired-case tests use `now - 1s`, all valid-case tests use `now + 7d`. Confirms the P1 AC6 spec-precision gap above. |
| 3 | `app/services/group_service.py:280` (`_require_owner`) | `!= GroupRole.OWNER` → `== GroupRole.OWNER` (inverts which role passes the Owner-only gate) | ✅ Killed — 56 tests failed across nearly every management endpoint |
| 4 | `app/services/group_service.py:243-244` (`transfer_ownership`) | Swapped call order: promote-new-owner-first instead of demote-old-owner-first | ✅ Killed — unit test's call-order assertion failed AND, more importantly, the router-level integration test hit a real Postgres `IntegrityError: duplicate key value violates unique constraint "ix_group_memberships_one_owner_per_group"` — empirically confirms Phase 3's ordering claim is a real DB-enforced requirement, not just convention |
| 5 | `app/services/group_service.py:15` (`_INVITE_RATE_LIMIT_MAX`) | `10` → `11` | ✅ Killed — both `test_eleventh_invite_within_window_is_rate_limited` (unit) and `test_eleventh_invite_in_one_hour_returns_429` (integration) failed |

**Sensor depth**: lightweight (5 targeted mutations, default tier)
**Result**: 4/5 killed — ⚠️ 1 survived (mutation 2)

---

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code | ✅ — every method traces to a spec AC or a named design decision (AD-018/019/020/021) |
| Surgical changes | ✅ — `tasks.py`/`attachments.py` changes are the minimal single-point extension (`_get_owned_project_id`→`_get_accessible_project_id`) called out in design.md; no unrelated refactors found |
| No scope creep | ✅ — no "Viewer" role, no multi-group linkage, no email — Out of Scope table honored throughout the diff |
| Matches patterns | ✅ — `GroupService`/`groups.py` mirror `ProjectService`/`projects.py` structure exactly (factory dependency, try/except → HTTPException mapping, AD-011 flush-only repositories + service-owned commit) |
| Spec-anchored outcome check (asserted values match spec-defined outcome) | ⚠️ — one confirmed mismatch (P2 AC5, 410-vs-404), documented above |
| Per-layer Coverage Expectation met (domain 1:1 ACs; routes happy+edge+error) | ⚠️ — mostly met; two coverage sub-gaps found (P2 AC1's "tasks remain" claim, T1's matrix-required unit tests for the extracted token helpers) |
| Every test maps to a spec requirement — no unclaimed tests | ✅ — spot-checked `test_group_service.py` and `test_groups_router.py` in full; every test class name maps directly to a GRP-NN concern |
| Documented guidelines followed | `.specs/features/groups-rbac/tasks.md`'s Test Coverage Matrix (no separate `AGENTS.md`/`CONTRIBUTING.md` found) — followed for all layers except the T1 core/security.py unit-test line item (see above) |

**Additional spot-check notes**:
- `app/repositories/group_repository.py`: `create()`'s comment explaining why `group_id` is pre-generated (to flush group+membership together) is accurate and non-obvious — good documentation of a real subtlety, not filler.
- `app/services/group_service.py`: `transfer_ownership`'s comment about demote-then-promote ordering is not just asserted but empirically true (confirmed by sensor mutation 4) — rare case of a code comment that is independently verifiable.
- `app/api/routers/groups.py`: consistent exception→HTTP mapping pattern across all 13 endpoints, matching `projects.py`'s established style; no duplicated logic that should have been extracted (each handler's try/except block is short enough to stay inline, consistent with the rest of the codebase).
- No dead code, no debug prints/leftover TODOs found in any of the reviewed files.

---

## Gate Check

- **Gate command**: `uv run alembic upgrade head && uv run pytest -q && uv run pip-audit`
- **Result**: 335 passed, 0 failed, 0 skipped; migration at head cleanly; pip-audit: "No known vulnerabilities found"
- **Test count before feature**: 201 (per `.specs/STATE.md` Handoff, pre-groups-rbac baseline)
- **Test count after feature**: 335
- **Delta**: +134 (AD-021 pagination retrofit tests on `/projects` and `/tasks` + all groups-rbac T1-T16 tests — explicable, no unexplained shrinkage)
- **Skipped tests**: none
- **Failures**: none

---

## Non-Regression Check (AD-018)

Confirmed explicitly, not just "still green":

- `ProjectRepository.get_for_user`/the strict path is byte-for-byte unchanged in `app/repositories/project_repository.py:83-87` — still used exclusively by `ProjectService.rename`/`delete` (`app/services/project_service.py`, unchanged call sites) and by `GroupService.link_project`'s ownership check (`app/services/group_service.py:254`, intentionally strict per design.md).
- Reduction-to-old-behavior explicitly tested: `tests/integration/repositories/test_project_repository.py::TestProjectRepositoryListAccessibleForUser::test_list_accessible_for_user_regression_matches_old_strict_behavior_with_no_groups` — a user with zero groups gets the identical project set/total from `list_accessible_for_user` as the old strict `list_for_user` did.
- `tests/integration/api/test_auth_boundary.py` and `tests/integration/api/test_auth_router.py`: **zero diff** in the full `0f3dd85..HEAD` range — confirmed unchanged, not weakened, and passing.
- `tests/integration/api/test_projects_router.py`, `test_tasks_router.py`, `test_attachments_router.py`: diffs reviewed line-by-line — every change is either (a) unwrapping the new `Page[T]` envelope (`.json()["items"]` instead of `.json()`) to accommodate AD-021's breaking pagination change, or (b) new tests added. No existing assertion was weakened, relaxed, or deleted.
- `TestGroupMemberTaskAccess` (both tests) is the spec's Independent Test made real: Member gets full CRUD via the actual `/projects/{id}/tasks/...` endpoints; a genuinely separate third user gets 404 on the same endpoints — proving additive-only access, confirmed further by Sensor mutation 1 (removing the group branch breaks only group-member paths, not owner paths).

**Non-regression: confirmed.**

---

## Fix Plans

### Fix 1: P2 AC5 spec/implementation mismatch (410 vs 404 for revoked invites)
- **Root cause**: spec.md's literal text for P2 AC5 says "uso subsequente retorna 410," but design.md's Error Handling Strategy table (approved) deliberately maps revoked tokens to the same 404 as unknown tokens, to avoid leaking which case applies (an AD-012-consistent security choice). The two documents were never reconciled.
- **Fix task**: Either (a) update spec.md's P2 AC5 text to say 404 and add a one-line rationale note matching design.md's existing table, or (b) if 410 is genuinely wanted for revoked-specifically (accepting the minor existence-leak of "revoked vs never-existed"), change `accept_invite`'s revoked-token branch to raise a distinct exception mapped to 410. Given AD-012's precedent elsewhere in this codebase, (a) is almost certainly the right fix — it's a documentation-only change, not a code change.
- **Priority**: Minor (behavior is defensible and consistent with the rest of the codebase's security posture; the gap is a documentation inconsistency, not a functional defect).

### Fix 2: Untested boundary — invite expiry at the exact instant
- **Root cause**: no test constructs an invite whose `expires_at` equals `now` at check time; `accept_invite`'s `invite.expires_at < now` vs `<= now` distinction is unverified.
- **Fix task**: Add one unit test in `TestAcceptInvite` (`tests/unit/services/test_group_service.py`) freezing/injecting `expires_at == now` (e.g. via a fixed `datetime` and monkeypatching `datetime.now` or accepting a small tolerance window) to pin down whether the exact boundary should expire or not, then assert accordingly.
- **Priority**: Minor.

### Fix 3: P2 AC1's "tasks remain" and "access revoked immediately" sub-claims untested
- **Root cause**: `test_remove_member_by_owner_returns_204_and_revokes_access` only checks the `/members` listing count; it never has the removed member attempt a task-level request, and never checks that a task the removed member created is still visible to the owner afterward.
- **Fix task**: Extend the test (or add a new one in `test_tasks_router.py`) that: (1) has a member create a task on a group-linked project, (2) owner removes that member, (3) removed member's subsequent `GET /projects/{id}/tasks` returns 404, (4) owner's `GET /projects/{id}/tasks` still shows the task the removed member created.
- **Priority**: Minor (the underlying mechanism — live membership lookup with no caching — makes both claims architecturally sound; this is a coverage gap, not a suspected defect).

### Fix 4: Edge case — invite outlives its deleted group
- **Root cause**: no test exercises "generate invite → delete group (only possible with 0 linked projects) → accept → 404."
- **Fix task**: Add an integration test in `test_groups_router.py` covering this sequence.
- **Priority**: Minor (structurally guaranteed by the FK `ondelete="CASCADE"`, but the spec explicitly calls this edge case out by name, so it deserves direct proof).

### Fix 5: T1's coverage-matrix gap — no direct unit test for `generate_opaque_token`/`hash_token`
- **Root cause**: `tests/unit/core/test_security.py` was never extended with tests for the two functions extracted in T1, even though the Test Coverage Matrix in tasks.md explicitly calls for "Deterministic hash, token format/entropy" unit coverage.
- **Fix task**: Add a `TestOpaqueToken` class to `tests/unit/core/test_security.py`: assert `hash_token(x) == hash_token(x)` (deterministic), `hash_token(x) != x` (not identity), `generate_opaque_token()` returns a non-empty URL-safe string of expected length, and two calls produce different tokens (entropy).
- **Priority**: Minor.

None of these gaps are blockers — the feature's core promise (P1 Independent Test, AD-018 non-regression) is proven end-to-end with strong evidence. All 5 are coverage/documentation gaps, not confirmed functional defects, except Fix 1 which is a genuine spec-text vs. implementation inconsistency that should be reconciled in the documentation.

---

## Requirement Traceability Update

| Requirement | Previous Status | New Status |
| --- | --- | --- |
| GRP-01 | Implementing | ✅ Verified |
| GRP-02 | Implementing | ✅ Verified |
| GRP-03 | Implementing | ✅ Verified |
| GRP-04 | Implementing | ✅ Verified |
| GRP-05 | Implementing | ✅ Verified |
| GRP-06 | Implementing | ✅ Verified |
| GRP-07 | Implementing | ⚠️ Verified with gap (see Fix 3) |
| GRP-08 | Implementing | ✅ Verified |
| GRP-09 | Implementing | ✅ Verified |
| GRP-10 | Implementing | ⚠️ Verified with gap (see Fix 1) |
| GRP-11 | Implementing | ✅ Verified |
| GRP-12 | Implementing | ⚠️ Verified with gap (see Fix 4 for the cascade sub-case) |
| GRP-13 | Implementing | ✅ Verified |
| GRP-14 | Implementing | ✅ Verified |
| GRP-15 | Implementing | ✅ Verified |

---

## Summary

**Overall**: ⚠️ Issues (minor, non-blocking)

**Spec-anchored check**: 22/24 ACs matched spec outcome exactly; 1 confirmed spec/implementation mismatch (P2 AC5); 2 spec-precision gaps (P1 AC6 boundary, P2 AC8 cascade proof); 1 AC with an uncovered sub-claim (P2 AC1)

**Sensor**: 4/5 mutations killed; 1 survived (invite expiry exact-boundary — directly corroborates the P1 AC6 spec-precision gap found independently in the AC pass)

**Gate**: 335 passed, 0 failed (baseline 201, delta +134); migration clean; pip-audit clean

**What works**: The feature's entire P1 happy path (create group → invite → accept → link project → Member CRUDs tasks → non-member still blocked) is proven end-to-end through real HTTP calls in `TestGroupMemberTaskAccess` and the broader `test_groups_router.py` suite (834 lines, 55+ test methods). AD-018's additive-only guarantee is proven both by direct regression test and by the discrimination sensor (removing the group branch breaks only group-member paths). Transfer-ownership atomicity is proven not just asserted — the sensor caught a real Postgres constraint violation when the required call order was reversed. Every P2 management action correctly returns 403 for non-owner Members (9 separate tests). RBAC pattern is architecturally consistent with AD-012/AD-014/AD-011.

**Issues found**:
1. P2 AC5: spec.md text says 410, implementation/tests say 404 — reconcile spec.md (Fix 1).
2. Invite expiry's exact boundary instant is untested and a mutation there survives (Fix 2).
3. "Removed member loses task access" and "removed member's tasks stay" are asserted by the spec but not proven by a task-level test (Fix 3).
4. "Invite outlives deleted group" edge case has no test (Fix 4).
5. T1's extracted token-helper functions lack the direct unit tests the Test Coverage Matrix calls for (Fix 5).

**Next steps**: All 5 fixes are minor/documentation-weight and do not block shipping the feature; recommend a follow-up task batching Fixes 1-5 (mostly test additions + one doc reconciliation) rather than blocking on them now.

---

## Lessons

1. **Diff-range instructions can be wrong relative to actual git history — verify before scoping.** The task brief said "the feature started after commit `e292064`," but `e292064` was a mid-feature docs commit (recording AD-020/021) that landed *after* T1-T4 had already been committed. Trusting the stated range would have silently excluded the security-extraction, models, and migration tasks from review. General lesson: when a Verifier is given a diff range as a starting hypothesis, confirm it against `git log` before treating it as ground truth — a stated commit boundary in a handoff note is not authoritative over the actual commit graph.

2. **A spec's literal status-code text and an approved design.md can drift without either document being updated to match.** P2 AC5 in spec.md says 410; design.md's Error Handling Strategy table (written later, in the same feature's Design phase) says 404 for the same scenario, with a deliberate security rationale (not leaking revoked-vs-unknown). The implementation correctly followed design.md, but nothing flagged spec.md as needing a matching update. General lesson: when Design phase makes a deliberate outcome choice that differs from an already-written spec AC (even for good reason), the spec should be updated in the same commit/phase — otherwise a later Verifier has no way to tell "intentional divergence" from "implementation bug" without reading both documents side by side.

3. **A boundary condition with no test at the boundary is a real, cheap-to-close gap — and the discrimination sensor is the fastest way to find it.** Scanning the code for `<` vs `<=` comparisons and checking whether any test uses a value *at* that boundary (not just clearly on either side) caught a genuine untested edge in under one mutation cycle. General lesson: for any time/count-based comparison in a spec-driven feature (expiry, rate limits, size limits), the discrimination sensor should specifically target the exact boundary value, not just "before" and "after" — tests built from acceptance criteria tend to use comfortably-clear-cut examples and skip the instant where the operator itself matters.
