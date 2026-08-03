# LESSONS — auto-maintained by scripts/lessons.py

> Machine-owned. Do NOT hand-edit. Changes are overwritten on the next `lessons.py` write.
> Canonical state lives in `.specs/lessons.json`. Edit lessons only via the script.
> promote_threshold=2 distinct features · window_days=45 · quarantine_threshold=2

## Confirmed (load these at Specify/Design)

Corroborated across multiple features. Safe to apply as guidance.

_none_

## Candidates (under observation — do NOT load as guidance yet)

Seen once or not yet corroborated. Tracked, not trusted.

### L-001 — Deleting a parent entity must also clean up its dependent external resources (e.g., storage files), not just rely on DB cascade-delete for child rows.
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `services` · harmful: 0
- features: taskly-api
- evidence: TASK-04 (services)
- last seen: 2026-07-24T11:07:34Z

### L-002 — Assert security-sensitive response headers (e.g., Set-Cookie HttpOnly/SameSite flags) by parsing the actual raw header value, not via a convenience client that discards attributes.
- signal: `surviving_mutant` · recurrence: 1 feature(s) · scope: `auth` · harmful: 0
- features: taskly-api
- evidence: app/api/routers/auth.py:96 (httponly=True removal mutant survived initially) (auth)
- last seen: 2026-07-24T11:07:34Z

### L-003 — Every explicitly listed spec edge case needs its own test, even when the expected behavior seems automatic (e.g., via framework/schema type validation).
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `validation` · harmful: 0
- features: taskly-api
- evidence: TASK P1 AC-6 (prazo em formato inválido -> 422) (validation)
- last seen: 2026-07-24T11:07:34Z

### L-004 — When an auth-boundary rule applies to many routes, test it against every protected route explicitly (parametrized), not just one representative route.
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `auth` · harmful: 0
- features: taskly-api
- evidence: ISO-01 (auth)
- last seen: 2026-07-24T11:07:34Z

### L-005 — Assert domain-error details (e.g., which specific field/value failed validation) at the HTTP response boundary, not only at the unit/service-test level.
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `api-errors` · harmful: 0
- features: taskly-api
- evidence: TAG-02 (api-errors)
- last seen: 2026-07-24T11:07:35Z

### L-006 — Field length/boundary constraints stated in the spec need explicit boundary tests (min, max, over-limit), not just happy-path values.
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `validation` · harmful: 0
- features: taskly-api
- evidence: PROJ-01 (validation)
- last seen: 2026-07-24T11:07:35Z

### L-007 — When an ownership check spans multiple layers/parameters in a nested route (e.g. project_id from URL + child resource id), add a router/e2e-level test for the specific combination where the outer id is genuinely owned by the caller but the inner id belongs to a different parent, not just a repository-unit test for that combination.
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `routes` · harmful: 0
- features: taskly-api
- evidence: tests/integration/api/test_tasks_router.py (ISO-02, router layer) (routes)
- last seen: 2026-07-24T12:21:34Z

### L-008 — When a spec AC names a stronger-sounding term than what a weaker synonym would satisfy (e.g. URL vs. reference/identifier), write the test to exercise the field at that literal strength — actually dereference a returned URL and assert on real content or a redirect — not just assert the field is present or non-empty.
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `attachments` · harmful: 0
- features: taskly-api
- evidence: ATT-01 (attachments)
- last seen: 2026-07-24T17:59:12Z

### L-009 — When design.md intentionally overrides a spec.md AC for a security-consistency reason (e.g. 404 instead of 410 to avoid leaking revoked-vs-unknown), update spec.md in the same phase — otherwise a later Verifier can't tell intentional divergence from a bug.
- signal: `spec_deviation` · recurrence: 1 feature(s) · scope: `backend` · harmful: 0
- features: groups-rbac
- evidence: spec.md P2 AC5 (backend)
- last seen: 2026-08-03T01:34:01Z

### L-010 — For time/count boundary comparisons, add a discrimination-sensor mutation at the exact boundary value, not just clearly-before/clearly-after — that is where spec-driven test suites tend to have blind spots.
- signal: `surviving_mutant` · recurrence: 1 feature(s) · scope: `backend` · harmful: 0
- features: groups-rbac
- evidence: app/services/group_service.py accept_invite expiry check (backend)
- last seen: 2026-08-03T01:34:01Z

## Quarantined (failed when applied — ignore)

A confirmed lesson that recurred alongside failure. Kept for the maintainer to review.

_none_
