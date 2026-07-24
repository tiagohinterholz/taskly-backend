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

## Quarantined (failed when applied — ignore)

A confirmed lesson that recurred alongside failure. Kept for the maintainer to review.

_none_
