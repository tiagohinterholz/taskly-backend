# Groups & RBAC Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `tlc-spec-driven` skill: **activate it by
name and follow its Execute flow and Critical Rules.** Do not search for
skill files by filesystem path. The skill is the source of truth for the
full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier,
discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not
proceed without it.**

---

**Design**: `.specs/features/groups-rbac/design.md`
**Status**: Approved

---

## Test Coverage Matrix

> Generated from codebase sampling (`tests/unit/services/`,
> `tests/integration/repositories/`, `tests/integration/api/`,
> `tests/unit/core/test_security.py`) and `.github/workflows/deploy.yml`.
> No `AGENTS.md`/`CONTRIBUTING.md` testing guideline file found — depth
> below follows the repo's own existing sample depth (which already meets
> the strong default: unit tests 1:1 to service branches, integration
> tests covering happy + edge + error paths per router).

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| --- | --- | --- | --- | --- |
| Service (`GroupService`, extended `AuthService`) | unit | All branches; 1:1 to spec ACs (GRP-01..15); every listed edge case | `tests/unit/services/test_group_service.py` | `uv run pytest tests/unit -q` |
| `core/security.py` utilities (`generate_opaque_token`/`hash_token`) | unit | Deterministic hash, token format/entropy, existing refresh-token unit tests still pass unchanged | `tests/unit/core/test_security.py` | `uv run pytest tests/unit -q` |
| Repository (`GroupRepository`, `GroupInviteRepository`, `ProjectRepository` extension) | integration | Key query paths + error/empty-result handling, against a real test DB (matches existing repo tests) | `tests/integration/repositories/test_group_repository.py`, `test_group_invite_repository.py`, `test_project_repository.py` | `uv run pytest tests/integration/repositories -q` |
| Router (`groups.py`, plus the `tasks.py`/`attachments.py` integration point) | integration | All routes in scope: happy path + every edge case in spec + error paths (403/404/409/410/422/429) | `tests/integration/api/test_groups_router.py`, existing `test_tasks_router.py`/`test_attachments_router.py` (regression) | `uv run pytest tests/integration/api -q` |
| Models (`Group`, `GroupMembership`, `GroupInvite`, `Project.group_id`) + Alembic migration | none | Build/migration gate only | — | `uv run alembic upgrade head` |

## Parallelism Assessment

> Generated from codebase — confirm before Execute.

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --- | --- | --- | --- |
| unit (services, core) | Yes | Repositories/session fully mocked, no shared backing store | `tests/unit/services/test_project_service.py` uses fakes, no DB |
| integration (repositories, routers) | No | Shared Postgres test DB with table-level cleanup between tests (`tests/integration/conftest.py`) | Existing conftest truncates tables in setup/teardown — concurrent tests would race on shared rows |

## Gate Check Commands

> Generated from codebase (`.github/workflows/deploy.yml` test job) — confirm before Execute.

| Gate Level | When to Use | Command |
| --- | --- | --- |
| Quick | After tasks touching only unit-tested layers (service/core) | `uv run pytest tests/unit -q` |
| Full | After tasks touching integration-tested layers (repository/router) | `uv run pytest -q` |
| Build | After phase completion, or any task touching models/migration | `uv run alembic upgrade head && uv run pytest -q && uv run pip-audit` |

---

## Execution Plan

### Phase 1: Foundation — security utility, models, migration (Sequential)

```
T1 → T2 → T3 → T4
```

### Phase 2: Repositories (Parallel OK, after Phase 1)

```
        ┌→ T5 [P] ─┐
T4 ─────┼→ T6 [P] ─┼──→ (Phase 3)
        └→ T7 [P] ─┘
```

### Phase 3: Service layer (Sequential — same file, incremental build-up)

```
T5,T6,T7 → T8 → T9 → T10 → T11
```

### Phase 4: Router layer (Sequential — same file)

```
T11 → T12 → T13 → T14 → T15
```

### Phase 5: Integration & wiring (Sequential)

```
T15 → T16
```

---

## Task Breakdown

### T1: Extract opaque-token helpers into `core/security.py`

**What**: Add `generate_opaque_token() -> str` and `hash_token(token: str) -> str` to `app/core/security.py` (same implementation as `AuthService`'s current inline `secrets.token_urlsafe(32)` / `hashlib.sha256(...).hexdigest()`); refactor `AuthService` to call them instead of its private `_hash_token`/inline call.
**Where**: `app/core/security.py`, `app/services/auth_service.py`
**Depends on**: None
**Reuses**: Exact algorithm already in `app/services/auth_service.py:118-126`
**Requirement**: AD-019 (design decision, not a GRP requirement directly — foundation for GRP-02/03)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `generate_opaque_token`/`hash_token` exist in `core/security.py` with the same behavior as the old inline code
- [ ] `AuthService` uses the extracted functions; its own `_hash_token` removed
- [ ] All existing `tests/unit/services/test_auth_service.py` and `tests/unit/core/test_security.py` pass unchanged (refactor, not a behavior change)
- [ ] Gate check passes: `uv run pytest tests/unit -q`

**Tests**: unit
**Gate**: quick
**Commit**: `refactor(security): extract opaque-token generation into core/security.py`

---

### T2: `Group`, `GroupRole`, `GroupMembership`, `GroupInvite` models

**What**: Create `app/models/group.py` with `GroupRole(str, enum.Enum)`, `Group`, `GroupMembership` (with `UniqueConstraint(group_id, user_id)` and a partial unique index on `group_id` where `role='owner'`), `GroupInvite` (mirrors `RefreshToken`'s shape: `token_hash`, `expires_at`, plus `consumed_at`/`revoked_at`). Register all in `app/models/__init__.py`.
**Where**: `app/models/group.py`, `app/models/__init__.py`
**Depends on**: None
**Reuses**: `app/models/task.py` (enum pattern), `app/models/refresh_token.py` (token model shape)
**Requirement**: GRP-01, GRP-02 (data model)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] Models match the Data Models section of `design.md` exactly (fields, FKs, constraints)
- [ ] Partial unique index (`group_id` WHERE `role='owner'`) is expressed via `sa.Index(..., postgresql_where=...)` or equivalent
- [ ] `app/models/__init__.py` exports the 4 new symbols
- [ ] Gate check passes: `uv run pytest tests/unit -q` (no regressions — models alone have no tests per matrix)

**Tests**: none (entity layer — covered indirectly by T4's migration + T5/T6/T7's repository tests)
**Gate**: quick
**Commit**: `feat(models): add Group, GroupMembership, GroupInvite`

---

### T3: `Project.group_id` column

**What**: Add nullable `group_id: uuid.UUID | None` FK column to `app/models/project.py`, `ForeignKey("groups.id", ondelete="RESTRICT")`, indexed.
**Where**: `app/models/project.py`
**Depends on**: T2 (needs `groups` table to reference)
**Reuses**: Existing `user_id` FK column pattern on the same model

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `Project.group_id` added exactly as specified in `design.md`
- [ ] Gate check passes: `uv run pytest tests/unit -q`

**Tests**: none (entity layer)
**Gate**: quick
**Commit**: `feat(models): add nullable group_id to Project`

---

### T4: Alembic migration

**What**: Generate a new Alembic revision (chained on top of `1c6ee173a43c_init`) creating `groups`, `group_memberships` (incl. the partial unique index), `group_invites`, and altering `projects` to add `group_id` with `ON DELETE RESTRICT`.
**Where**: `alembic/versions/<new_revision>_groups_rbac.py`
**Depends on**: T2, T3
**Reuses**: Structure of `alembic/versions/1c6ee173a43c_init.py`

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `uv run alembic upgrade head` succeeds against a clean test DB
- [ ] `uv run alembic downgrade -1` succeeds and cleanly reverses the migration
- [ ] Partial unique index verified present via `\d group_memberships` (or equivalent) after upgrade
- [ ] Gate check passes: `uv run alembic upgrade head && uv run pytest -q`

**Tests**: none (migration — covered by the build gate + downstream repository integration tests)
**Gate**: build
**Commit**: `feat(db): migration for groups, group_memberships, group_invites, projects.group_id`

---

### T5: `GroupRepository` [P]

**What**: Implement `app/repositories/group_repository.py` per `design.md`'s interface list (`create`, `get_membership`, `list_members`, `list_for_user`, `add_member`, `remove_member`, `set_role`, `count_linked_projects`), inheriting `BaseRepository[Group]`.
**Where**: `app/repositories/group_repository.py`, `tests/integration/repositories/test_group_repository.py`
**Depends on**: T4
**Reuses**: `app/repositories/base.py`, `app/repositories/project_repository.py` (query style)
**Requirement**: GRP-01, GRP-06, GRP-07, GRP-09, GRP-12, GRP-14

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] Every interface method from `design.md` implemented
- [ ] `create` atomically creates the group AND the Owner membership
- [ ] Integration tests cover: create+owner-membership, list_members, list_for_user (multi-group), add/remove member, set_role (ownership transfer scenario), count_linked_projects (0 and >0)
- [ ] Gate check passes: `uv run pytest tests/integration/repositories -q`

**Tests**: integration
**Gate**: full
**Commit**: `feat(repositories): add GroupRepository`

---

### T6: `GroupInviteRepository` [P]

**What**: Implement `app/repositories/group_invite_repository.py` per `design.md` (`create`, `get_by_hash`, `list_pending`, `mark_consumed`, `mark_revoked`), inheriting `BaseRepository[GroupInvite]`.
**Where**: `app/repositories/group_invite_repository.py`, `tests/integration/repositories/test_group_invite_repository.py`
**Depends on**: T4
**Reuses**: `app/repositories/refresh_token_repository.py` (near-identical shape)
**Requirement**: GRP-02, GRP-03, GRP-10, GRP-15

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] Every interface method implemented
- [ ] `list_pending` excludes consumed, revoked, AND expired invites
- [ ] Integration tests cover: create+get_by_hash roundtrip, list_pending (mixed states), mark_consumed, mark_revoked
- [ ] Gate check passes: `uv run pytest tests/integration/repositories -q`

**Tests**: integration
**Gate**: full
**Commit**: `feat(repositories): add GroupInviteRepository`

---

### T7: `ProjectRepository` extension — `get_accessible_for_user`/`list_accessible_for_user` [P]

**What**: Add `get_accessible_for_user(project_id, user_id)` and rename `list_for_user`→`list_accessible_for_user` (query expanded per AD-018: owner OR group member). Leave `get_for_user` untouched. Update `ProjectService.list_for_user`'s single call site.
**Where**: `app/repositories/project_repository.py`, `app/services/project_service.py`, `tests/integration/repositories/test_project_repository.py`
**Depends on**: T4
**Reuses**: Existing `get_for_user`/`list_for_user` query style in the same file
**Requirement**: GRP-04, GRP-05 (foundation for)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `get_accessible_for_user` returns the project for the direct owner, for a group member, and `None` for neither
- [ ] `list_accessible_for_user` returns direct + group-accessible projects, no duplicates if somehow both true
- [ ] **Regression**: a user with zero groups gets identical results from `list_accessible_for_user` as the old `list_for_user` did (v1 behavior preserved)
- [ ] `get_for_user` (strict) behavior/tests untouched — `ProjectService.rename`/`delete` still reject non-owners including group members
- [ ] Gate check passes: `uv run pytest tests/integration/repositories -q && uv run pytest tests/unit -q`

**Tests**: integration
**Gate**: full
**Commit**: `feat(repositories): add group-aware project access alongside strict ownership checks`

---

### T8: `GroupService` — group lifecycle

**What**: Implement `create`, `rename`, `delete` (with `GroupHasProjectsError` guard), `list_for_user`, `list_members` on `app/services/group_service.py`. Domain exceptions: `GroupNotFoundError`, `NotGroupOwnerError`, `GroupHasProjectsError`.
**Where**: `app/services/group_service.py`, `tests/unit/services/test_group_service.py`
**Depends on**: T5
**Reuses**: `app/services/project_service.py` (exception + transaction pattern)
**Requirement**: GRP-01, GRP-06, GRP-12, GRP-13, GRP-14

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] All 5 methods implemented per spec ACs (P1 AC1, P2 AC7/8/9)
- [ ] Unit tests: create→owner assigned; rename by non-owner raises `NotGroupOwnerError`; delete blocked when `count_linked_projects>0`; delete succeeds at 0; list_for_user/list_members happy paths
- [ ] Gate check passes: `uv run pytest tests/unit -q`

**Tests**: unit
**Gate**: quick
**Commit**: `feat(services): GroupService group lifecycle (create/rename/delete/list)`

---

### T9: `GroupService` — invite lifecycle

**What**: Add `create_invite`, `accept_invite`, `revoke_invite`, `list_pending_invites` to `GroupService`, using `generate_opaque_token`/`hash_token` (T1) and a shared-dict rate limiter (10/hour/owner, mirroring `AuthService`'s pattern). Domain exceptions: `InviteNotFoundError`, `InviteExpiredError`, `InviteAlreadyUsedError`, `AlreadyMemberError`, `InviteRateLimitExceededError`.
**Where**: `app/services/group_service.py`, `tests/unit/services/test_group_service.py`
**Depends on**: T8, T6, T1
**Reuses**: `app/api/routers/auth.py`'s `_shared_failed_attempts` module-level dict pattern
**Requirement**: GRP-02, GRP-03, GRP-10, GRP-15

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `create_invite` by non-owner raises `NotGroupOwnerError`; 11th invite in <1h raises `InviteRateLimitExceededError`
- [ ] `accept_invite`: valid token → membership created + `consumed_at` set; already-consumed → `InviteAlreadyUsedError`; expired → `InviteExpiredError`; revoked/unknown → `InviteNotFoundError`; already-a-member → `AlreadyMemberError`
- [ ] `revoke_invite` by non-owner raises `NotGroupOwnerError`; revoked token then fails accept with `InviteNotFoundError`
- [ ] Unit tests cover every branch above (spec edge cases from "Edge Cases" section)
- [ ] Gate check passes: `uv run pytest tests/unit -q`

**Tests**: unit
**Gate**: quick
**Commit**: `feat(services): GroupService invite lifecycle (create/accept/revoke/list)`

---

### T10: `GroupService` — membership & ownership management

**What**: Add `remove_member`, `leave`, `transfer_ownership` to `GroupService`. Domain exceptions: `NotGroupMemberError`, `SoleOwnerCannotLeaveError`.
**Where**: `app/services/group_service.py`, `tests/unit/services/test_group_service.py`
**Depends on**: T8
**Reuses**: `GroupRepository.set_role` (T5) for the atomic swap in `transfer_ownership`
**Requirement**: GRP-07, GRP-08, GRP-09

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `remove_member` by non-owner raises `NotGroupOwnerError`; removed member's tasks stay untouched (no cascading task deletion logic added — confirms design intent, not a new DB behavior to test here beyond "membership row gone")
- [ ] `leave` by the sole Owner raises `SoleOwnerCannotLeaveError`; by a Member succeeds
- [ ] `transfer_ownership` by non-owner raises `NotGroupOwnerError`; to a non-member raises `NotGroupMemberError`; happy path leaves exactly one Owner (old Owner becomes Member) in the same transaction
- [ ] Gate check passes: `uv run pytest tests/unit -q`

**Tests**: unit
**Gate**: quick
**Commit**: `feat(services): GroupService membership management (remove/leave/transfer-ownership)`

---

### T11: `GroupService` — project link/unlink

**What**: Add `link_project`, `unlink_project` to `GroupService`. Domain exceptions: `ProjectAlreadyLinkedError` (reuses `ProjectNotFoundError` from `project_service.py` for the not-owned/not-found case).
**Where**: `app/services/group_service.py`, `tests/unit/services/test_group_service.py`
**Depends on**: T8, T7
**Reuses**: `ProjectRepository.get_for_user` (T7, strict — confirms the acting user owns the project before linking)
**Requirement**: GRP-04, GRP-11

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `link_project` by non-owner raises `NotGroupOwnerError`; on a project the acting user doesn't own raises `ProjectNotFoundError`; on an already-linked (to another group) project raises `ProjectAlreadyLinkedError`; happy path sets `group_id`
- [ ] `unlink_project` by non-owner raises `NotGroupOwnerError`; happy path nulls `group_id`
- [ ] Gate check passes: `uv run pytest tests/unit -q`

**Tests**: unit
**Gate**: quick
**Commit**: `feat(services): GroupService project link/unlink`

---

### T12: `groups.py` router — group CRUD + members

**What**: `POST /groups`, `GET /groups`, `PATCH /groups/{group_id}`, `DELETE /groups/{group_id}`, `GET /groups/{group_id}/members`, wired to `GroupService` (T8), with request/response Pydantic models and domain-exception→HTTP mapping per `design.md`'s Error Handling Strategy table.
**Where**: `app/api/routers/groups.py`, `tests/integration/api/test_groups_router.py`
**Depends on**: T11 (full `GroupService` surface available; router built incrementally but service must compile)
**Reuses**: `app/api/routers/projects.py` (router skeleton, factory-dependency pattern, exception mapping style)
**Requirement**: GRP-01, GRP-06, GRP-12, GRP-13, GRP-14

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] All 5 endpoints implemented with `response_model`s matching `design.md`
- [ ] Integration tests: happy path per endpoint + 403 (non-owner) + 404 (unknown/foreign group) + 409 (delete with linked project) — per spec P1/P2 ACs
- [ ] Gate check passes: `uv run pytest tests/integration/api -q`

**Tests**: integration
**Gate**: full
**Commit**: `feat(api): groups router — CRUD + members`

---

### T13: `groups.py` router — invites

**What**: `POST /groups/{group_id}/invites`, `GET /groups/{group_id}/invites`, `DELETE /groups/{group_id}/invites/{invite_id}`, `POST /invites/{token}/accept`.
**Where**: `app/api/routers/groups.py`, `tests/integration/api/test_groups_router.py`
**Depends on**: T12
**Reuses**: Same router skeleton as T12
**Requirement**: GRP-02, GRP-03, GRP-10, GRP-15

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] All 4 endpoints implemented; invite-creation response includes the plain-text token exactly once
- [ ] Integration tests: generate→accept happy path; accept twice → 409; accept expired → 410; accept revoked → 404; non-owner generates → 403; 11th invite in window → 429; already-member accepts → 409
- [ ] Gate check passes: `uv run pytest tests/integration/api -q`

**Tests**: integration
**Gate**: full
**Commit**: `feat(api): groups router — invites`

---

### T14: `groups.py` router — membership management

**What**: `DELETE /groups/{group_id}/members/{user_id}`, `POST /groups/{group_id}/leave`, `POST /groups/{group_id}/transfer-ownership`.
**Where**: `app/api/routers/groups.py`, `tests/integration/api/test_groups_router.py`
**Depends on**: T13
**Reuses**: Same router skeleton
**Requirement**: GRP-07, GRP-08, GRP-09

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] All 3 endpoints implemented
- [ ] Integration tests: remove by non-owner → 403; owner leaves without transferring → 409; leave as member → 200; transfer to non-member → 404/422; transfer happy path confirmed via a follow-up `GET /members` showing swapped roles
- [ ] Gate check passes: `uv run pytest tests/integration/api -q`

**Tests**: integration
**Gate**: full
**Commit**: `feat(api): groups router — membership management`

---

### T15: `groups.py` router — project link/unlink

**What**: `POST /groups/{group_id}/projects/{project_id}/link`, `POST /groups/{group_id}/projects/{project_id}/unlink`.
**Where**: `app/api/routers/groups.py`, `tests/integration/api/test_groups_router.py`
**Depends on**: T14
**Reuses**: Same router skeleton
**Requirement**: GRP-04, GRP-11

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] Both endpoints implemented
- [ ] Integration tests: link by non-owner → 403; link a project the acting user doesn't own → 403/404; link an already-linked project → 409; happy path confirmed; unlink happy path confirmed
- [ ] Gate check passes: `uv run pytest tests/integration/api -q`

**Tests**: integration
**Gate**: full
**Commit**: `feat(api): groups router — project link/unlink`

---

### T16: Wire into `main.py` + extend task/attachment access + full regression

**What**: Register `groups_router` in `app/main.py`. Rename `_get_owned_project_id`→`_get_accessible_project_id` in `app/api/routers/tasks.py`, switch it to call `ProjectRepository.get_accessible_for_user` (T7); update the import in `app/api/routers/attachments.py`. Update `.specs/STATE.md` Handoff section for this feature.
**Where**: `app/main.py`, `app/api/routers/tasks.py`, `app/api/routers/attachments.py`
**Depends on**: T15
**Reuses**: T7's `get_accessible_for_user`
**Requirement**: GRP-05 (P1 AC10/AC11 — the actual RBAC enforcement on tasks)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `groups_router` registered; `GET /openapi.json` (or equivalent smoke check already used by `test_app_wiring.py`) lists the new routes
- [ ] **New integration test** (in `test_tasks_router.py` or a new file): a Member of a group can CRUD tasks on a project linked to that group; a non-member gets 403/404 on the same project — this is the story's core "no regression + real collaboration" proof (spec Success Criteria)
- [ ] **Regression**: full existing `test_tasks_router.py`/`test_attachments_router.py`/`test_auth_boundary.py` suites pass unchanged — v1 users with no groups see identical behavior
- [ ] Full suite test count reported (baseline 201 + new tests from T1-T16)
- [ ] Gate check passes: `uv run alembic upgrade head && uv run pytest -q && uv run pip-audit`

**Tests**: integration
**Gate**: build
**Commit**: `feat(api): wire groups into task/attachment authorization; register groups router`

---

## Parallel Execution Map

```
Phase 1 (Sequential):
  T1 ──→ T2 ──→ T3 ──→ T4

Phase 2 (Parallel):
  T4 complete, then:
    ├── T5 [P]
    ├── T6 [P]  } Can run simultaneously
    └── T7 [P]

Phase 3 (Sequential — same file, app/services/group_service.py):
  T5,T6,T7 complete, then:
    T8 ──→ T9 ──→ T10 ──→ T11

Phase 4 (Sequential — same file, app/api/routers/groups.py):
  T11 complete, then:
    T12 ──→ T13 ──→ T14 ──→ T15

Phase 5 (Sequential):
  T15 complete, then:
    T16
```

**Parallelism constraint:** A task marked `[P]` must have ALL of these:
- No unfinished dependencies
- Required test type is parallel-safe (per the Parallelism Assessment above)
- No shared mutable state with other `[P]` tasks in the same phase

T5/T6/T7 all touch integration tests (marked **not** parallel-safe in the
Parallelism Assessment table due to shared test-DB cleanup) — but they
touch **different files** with no code overlap, so `[P]` here means
"no inter-task code dependency," while their gate runs stay sequential in
practice (same `pytest` invocation serializes them anyway). This matches
how the skill defines `[P]`: ordering information, not a parallel-test-run
guarantee.

---

## Task Granularity Check

| Task | Scope | Status |
| --- | --- | --- |
| T1: Extract token helpers | 2 functions, 1 refactor | ✅ Granular |
| T2: Group/Membership/Invite models | 1 file, 4 related types (cohesive — one migration's worth of models) | ✅ Granular (2-3 related things, same file, cohesive) |
| T3: Project.group_id column | 1 field, 1 file | ✅ Granular |
| T4: Migration | 1 migration file | ✅ Granular |
| T5: GroupRepository | 1 repository class | ✅ Granular |
| T6: GroupInviteRepository | 1 repository class | ✅ Granular |
| T7: ProjectRepository extension | 2 methods, 1 file | ✅ Granular |
| T8: GroupService — lifecycle | 5 methods, 1 concern (group CRUD) | ✅ Granular (cohesive) |
| T9: GroupService — invites | 4 methods, 1 concern (invite lifecycle) | ✅ Granular (cohesive) |
| T10: GroupService — membership | 3 methods, 1 concern (membership mgmt) | ✅ Granular (cohesive) |
| T11: GroupService — project link | 2 methods, 1 concern | ✅ Granular |
| T12: groups.py — CRUD+members | 5 endpoints, 1 concern | ✅ Granular (cohesive) |
| T13: groups.py — invites | 4 endpoints, 1 concern | ✅ Granular (cohesive) |
| T14: groups.py — membership | 3 endpoints, 1 concern | ✅ Granular (cohesive) |
| T15: groups.py — link/unlink | 2 endpoints, 1 concern | ✅ Granular |
| T16: Wiring + regression | 3 files, 1 concern (integration point) | ✅ Granular |

---

## Diagram-Definition Cross-Check

| Task | Depends On (task body) | Diagram Shows | Status |
| --- | --- | --- | --- |
| T1 | None | None | ✅ Match |
| T2 | None | T1→T2 | ✅ Match (sequential phase, no code dependency but same-phase ordering) |
| T3 | T2 | T2→T3 | ✅ Match |
| T4 | T2, T3 | T3→T4 | ✅ Match |
| T5 | T4 | T4→T5 [P] | ✅ Match |
| T6 | T4 | T4→T6 [P] | ✅ Match |
| T7 | T4 | T4→T7 [P] | ✅ Match |
| T8 | T5 | T5,T6,T7→T8 | ✅ Match |
| T9 | T8, T6, T1 | T8→T9 | ✅ Match (T6/T1 already satisfied by Phase 2/1) |
| T10 | T8 | T9→T10 | ✅ Match |
| T11 | T8, T7 | T10→T11 | ✅ Match (T7 already satisfied by Phase 2) |
| T12 | T11 | T11→T12 | ✅ Match |
| T13 | T12 | T12→T13 | ✅ Match |
| T14 | T13 | T13→T14 | ✅ Match |
| T15 | T14 | T14→T15 | ✅ Match |
| T16 | T15 | T15→T16 | ✅ Match |

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| --- | --- | --- | --- | --- |
| T1 | Service (core/security.py + AuthService) | unit | unit | ✅ OK |
| T2 | Models | none | none | ✅ OK |
| T3 | Models | none | none | ✅ OK |
| T4 | Models/migration | none | none | ✅ OK |
| T5 | Repository | integration | integration | ✅ OK |
| T6 | Repository | integration | integration | ✅ OK |
| T7 | Repository | integration | integration | ✅ OK |
| T8 | Service | unit | unit | ✅ OK |
| T9 | Service | unit | unit | ✅ OK |
| T10 | Service | unit | unit | ✅ OK |
| T11 | Service | unit | unit | ✅ OK |
| T12 | Router | integration | integration | ✅ OK |
| T13 | Router | integration | integration | ✅ OK |
| T14 | Router | integration | integration | ✅ OK |
| T15 | Router | integration | integration | ✅ OK |
| T16 | Router (integration point) | integration | integration | ✅ OK |

---

## MCPs and Skills

No project or user MCP servers are configured for this session (confirmed
earlier in the project). No additional skills apply beyond `tlc-spec-driven`
itself driving Execute. All 16 tasks use standard file/Bash tools only.
