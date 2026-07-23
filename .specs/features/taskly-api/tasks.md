# Taskly API Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `tlc-spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Design**: `.specs/features/taskly-api/design.md`
**Status**: Draft

---

## Test Coverage Matrix

> Generated from Design phase decisions (projeto greenfield, sem código/testes existentes para amostrar). Guidelines found: none — sourced from `design.md` Tech Decisions (`AD-005`/`AD-009`: pytest unit+integration via `uv`), aplicando o strong default de cobertura por camada.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| --- | --- | --- | --- | --- |
| `core/security.py` (hash, JWT) | unit | Todos os branches: hash roundtrip, verify errado, decode expirado/malformado | `tests/unit/core/test_security.py` | `uv run pytest tests/unit -q` |
| `storage/*` (Local/S3 backend) | unit | save/delete happy path + falha, para as duas implementações | `tests/unit/storage/test_*.py` | `uv run pytest tests/unit -q` |
| `services/*` (regra de negócio) | unit | 1:1 com as ACs da spec; todos os edge cases listados; repository mockado | `tests/unit/services/test_*.py` | `uv run pytest tests/unit -q` |
| `repositories/*` (acesso a dados) | integration | Principais caminhos de query + tratamento de erro (constraint única, not found) | `tests/integration/repositories/test_*.py` | `uv run pytest tests/unit tests/integration -q` |
| `api/routers/*` (endpoints) | integration | Todas as rotas do escopo: happy path + edge cases + erro (401/404/409/422/413/429) | `tests/integration/api/test_*.py` | `uv run pytest tests/unit tests/integration -q` |
| `models/*`, `alembic/*`, `core/config.py` | none | — (build gate apenas) | — | build gate only |
| `Dockerfile` (multi-stage) | none | — (build gate apenas: build da imagem + container sobe como não-root) | — | build gate only |

## Parallelism Assessment

> Generated from Design decisions — sem código existente para inferir; regra aplicada por padrão do processo (sem isolamento de schema/transação definido, testes de integração batem no mesmo Postgres de teste → sequencial).

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --- | --- | --- | --- |
| unit | Yes | Cada teste mocka repository/storage/dependências externas; sem I/O real compartilhado | T4, T6, T9, T12, T14 não tocam Postgres nem storage real |
| integration | No | Testes de repository e router batem no mesmo Postgres de teste (`docker-compose` de teste); nenhum isolamento por schema/transação por teste foi definido no Design | T5, T8, T11 (repositories) e T7, T10, T13, T15 (routers) compartilham a mesma instância de banco de teste |

## Gate Check Commands

| Gate Level | When to Use | Command |
| --- | --- | --- |
| Quick | Após tasks com apenas testes unitários | `uv run pytest tests/unit -q` |
| Full | Após tasks com testes de integração | `uv run pytest tests/unit tests/integration -q` (requer Postgres de teste via `docker-compose`) |
| Build | Após conclusão de fase | `uv sync --locked && uv run pytest -q && uv run pip-audit` |

---

## Execution Plan

### Phase 1: Foundation (Sequential)

```
T1 → T2 → T3
```

### Phase 2: Cross-cutting utilities (Parallel OK)

```
T1 ──┬→ T4  [P]
     └→ T14 [P]
```

### Phase 3: Repositories (Sequential — banco de teste compartilhado)

```
T3 → T5 → T8 → T11
```

### Phase 4: Services (Parallel OK — unit tests, repository mockado)

```
        ┌→ T6  [P]  (depende de T4, T5)
T5,T8,T11┼→ T9  [P]  (depende de T8)
        └→ T12 [P]  (depende de T11)
```

### Phase 5: Routers (Sequential — banco de teste compartilhado)

```
T6 → T7 → T10 → T13 → T15
      ↑     ↑     ↑
     T7    T9    T12
   (dep)  (dep) (dep)
```

### Phase 6: Wiring (Sequential)

```
T7, T10, T13, T15 → T16
```

### Phase 7: Containerization (Sequential)

```
T16 → T17
```

---

## Task Breakdown

### T1: Setup do projeto com uv

**What**: Inicializar o projeto Python com `uv` (pyproject.toml, uv.lock), skeleton do app FastAPI com `/health`, `.env.example`, `.gitignore`.
**Where**: `pyproject.toml`, `uv.lock`, `app/main.py`, `.env.example`, `.gitignore`
**Depends on**: None
**Reuses**: n/a (greenfield)
**Requirement**: n/a (infra)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [x] `uv run fastapi dev` (ou uvicorn) sobe o app e `GET /health` retorna 200
- [x] `.env.example` documenta todas as env vars necessárias, sem valores reais
- [x] `uv.lock` versionado, dependências com versão fixada (sem `^`/`~`)
- [x] `uv run pip-audit` roda sem vulnerabilidade crítica/alta encontrada
- [x] `.gitignore` cobre `.venv/`, `__pycache__/`, `.env`

**Tests**: none
**Gate**: build

**Commit**: `chore(setup): initialize FastAPI project with uv`

---

### T2: Engine SQLAlchemy async + Alembic

**What**: Configurar engine async (SQLAlchemy 2.0 + `asyncpg`) lendo `DATABASE_URL` de env var, e inicializar Alembic.
**Where**: `app/core/db.py`, `alembic.ini`, `alembic/env.py`
**Depends on**: T1
**Reuses**: n/a
**Requirement**: n/a (infra)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [x] Engine conecta a um Postgres local (via `docker-compose.yml` de dev, a criar nesta task)
- [x] `uv run alembic revision --autogenerate -m "init"` roda sem erro (mesmo sem modelos ainda)
- [x] `uv run alembic upgrade head` aplica sem erro

**Tests**: none
**Gate**: build

**Commit**: `chore(db): configure async SQLAlchemy engine and Alembic`

---

### T3: Modelos ORM + migration inicial

**What**: Definir os 5 modelos (`User`, `RefreshToken`, `Project`, `Task`, `Attachment`) conforme `design.md` e gerar a migration inicial.
**Where**: `app/models/user.py`, `app/models/refresh_token.py`, `app/models/project.py`, `app/models/task.py`, `app/models/attachment.py`, `alembic/versions/xxxx_init.py`
**Depends on**: T2
**Reuses**: n/a
**Requirement**: n/a (schema — suporta AUTH/PROJ/TASK/ATT)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [x] Todos os campos, tipos, FKs, enum de `TaskStatus` e `ARRAY(String(20))` de tags conforme `design.md`
- [x] `uv run alembic upgrade head` cria o schema completo num Postgres limpo sem erro
- [x] Constraint de unicidade em `User.email` presente

**Tests**: none
**Gate**: build

**Commit**: `feat(models): add User, RefreshToken, Project, Task, Attachment models`

---

### T4: `PasswordHasher` + `JWTService` [P]

**What**: Utilitários puros de hashing de senha (`passlib[bcrypt]`) e encode/decode de JWT (`PyJWT`).
**Where**: `app/core/security.py`
**Depends on**: T1
**Reuses**: n/a
**Requirement**: AUTH-01 (suporte)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [x] `PasswordHasher.hash`/`verify` fazem roundtrip correto e rejeitam senha errada
- [x] `JWTService.encode`/`decode` retornam o `user_id` correto
- [x] `decode` levanta exceção clara para token expirado e para token malformado
- [x] Gate check passa: `uv run pytest tests/unit -q`
- [x] Test count: 4+ testes (hash ok, hash errado, decode expirado, decode malformado)

**Tests**: unit
**Gate**: quick

**Commit**: `feat(security): add password hashing and JWT service`

---

### T14: `StorageBackend` (protocolo) + implementações [P]

**What**: Protocolo `StorageBackend` com `save`/`delete`, mais `LocalStorageBackend` e `S3StorageBackend`, selecionáveis por env var `STORAGE_BACKEND`.
**Where**: `app/storage/backend.py`, `app/storage/local.py`, `app/storage/s3.py`
**Depends on**: T1
**Reuses**: n/a
**Requirement**: ATT-01 (suporte)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [x] `LocalStorageBackend.save`/`delete` testados com `tmp_path` (arquivo real gravado/removido)
- [x] `S3StorageBackend.save`/`delete` testados com `boto3` mockado (`moto` ou `unittest.mock`), incl. caso de falha do cliente S3
- [x] Seleção por `STORAGE_BACKEND` (`local`/`s3`) testada
- [x] Gate check passa: `uv run pytest tests/unit -q`
- [x] Test count: 6+ testes (save/delete × 2 implementações + falha + seleção)

**Tests**: unit
**Gate**: quick

**Commit**: `feat(storage): add StorageBackend abstraction with local and S3 implementations`

---

### T5: `UserRepository` + `RefreshTokenRepository`

**What**: Repositories de acesso a dados para usuário e refresh token.
**Where**: `app/repositories/user_repository.py`, `app/repositories/refresh_token_repository.py`
**Depends on**: T3
**Reuses**: n/a
**Requirement**: AUTH-01, AUTH-03 (suporte)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [x] `UserRepository.create`/`get_by_email` testados contra Postgres real, incl. violação de constraint única
- [x] `RefreshTokenRepository.create`/`get_by_hash`/`revoke` testados, incl. token expirado e já revogado
- [x] Gate check passa: `uv run pytest tests/unit tests/integration -q`
- [x] Test count: 6+ testes de integração

**Tests**: integration
**Gate**: full

**Commit**: `feat(repositories): add UserRepository and RefreshTokenRepository`

---

### T8: `ProjectRepository`

**What**: Repository de acesso a dados de projetos, com contagem de tarefas para a regra de bloqueio de delete.
**Where**: `app/repositories/project_repository.py`
**Depends on**: T3 (roda após T5 nesta fase — banco de teste compartilhado, sequencial)
**Reuses**: n/a
**Requirement**: PROJ-01..04 (suporte)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [x] `create`/`list_for_user`/`rename`/`delete`/`count_tasks` testados contra Postgres real
- [x] Isolamento por `user_id` coberto (usuário B não aparece na listagem de A)
- [x] Gate check passa: `uv run pytest tests/unit tests/integration -q`
- [x] Test count: 6+ testes de integração

**Tests**: integration
**Gate**: full

**Commit**: `feat(repositories): add ProjectRepository`

---

### T11: `TaskRepository`

**What**: Repository de acesso a dados de tarefas.
**Where**: `app/repositories/task_repository.py`
**Depends on**: T3 (roda após T8 nesta fase — banco de teste compartilhado, sequencial)
**Reuses**: n/a
**Requirement**: TASK-01..04, STAT-01, TAG-01 (suporte)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [x] `create`/`list_for_project`/`update`/`delete` testados contra Postgres real
- [x] Persistência correta de `tags` (array) e `status` (enum) coberta
- [x] Gate check passa: `uv run pytest tests/unit tests/integration -q`
- [x] Test count: 6+ testes de integração

**Tests**: integration
**Gate**: full

**Commit**: `feat(repositories): add TaskRepository`

---

### T6: `AuthService` [P]

**What**: Regras de negócio de autenticação — registro, login, refresh com rotação, logout, rate limit.
**Where**: `app/services/auth_service.py`
**Depends on**: T4, T5
**Reuses**: `PasswordHasher`, `JWTService` (T4), `UserRepository`, `RefreshTokenRepository` (T5, mockados nos testes)
**Requirement**: AUTH-01..05

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [x] `register` rejeita e-mail duplicado (repository mockado retornando conflito)
- [x] `authenticate` rejeita credenciais inválidas sem revelar se o e-mail existe
- [x] `refresh` rejeita token revogado/expirado e rotaciona corretamente em caso de sucesso
- [x] `logout` revoga o refresh token
- [x] Rate limit bloqueia após 5 tentativas falhas na mesma janela
- [x] Gate check passa: `uv run pytest tests/unit -q`
- [x] Test count: 8+ testes (1:1 com AUTH-01..05 + edge cases)

**Tests**: unit
**Gate**: quick

**Commit**: `feat(auth): add AuthService with registration, login, refresh rotation and rate limiting`

---

### T9: `ProjectService` [P]

**What**: Regras de negócio de projetos, incl. bloqueio de delete com tarefas.
**Where**: `app/services/project_service.py`
**Depends on**: T8
**Reuses**: `ProjectRepository` (mockado nos testes)
**Requirement**: PROJ-01..04

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [x] Criar, listar (só do usuário), renomear cobertos
- [x] Delete com tarefas associadas bloqueado (erro de domínio, mapeado a 409 no router)
- [x] Delete sem tarefas permitido
- [x] Gate check passa: `uv run pytest tests/unit -q`
- [x] Test count: 6+ testes (1:1 com PROJ-01..04)

**Tests**: unit
**Gate**: quick

**Commit**: `feat(projects): add ProjectService with delete-block rule`

---

### T12: `TaskService` [P]

**What**: Regras de negócio de tarefas — criação só com título, edição de qualquer campo, transições de status livres, validação de tags.
**Where**: `app/services/task_service.py`
**Depends on**: T11
**Reuses**: `TaskRepository` (mockado nos testes)
**Requirement**: TASK-01..04, STAT-01, TAG-01, TAG-02

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] Criação só com título aceita; título vazio rejeitado
- [ ] Edição de cada campo individualmente coberta
- [ ] Todas as transições de status testadas, incluindo "para trás" (ex.: `done` → `not_started`)
- [ ] Tag com 21+ caracteres rejeitada; tags válidas aceitas
- [ ] Gate check passa: `uv run pytest tests/unit -q`
- [ ] Test count: 10+ testes (1:1 com TASK-01..04, STAT-01, TAG-01/02)

**Tests**: unit
**Gate**: quick

**Commit**: `feat(tasks): add TaskService with free status transitions and tag validation`

---

### T7: Auth router + `get_current_user`

**What**: Endpoints `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout` e a dependency `get_current_user` usada por todos os routers protegidos.
**Where**: `app/api/routers/auth.py`, `app/api/dependencies.py`
**Depends on**: T6
**Reuses**: `AuthService` (T6)
**Requirement**: AUTH-01..05, ISO-01

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] E2E: registro 201, registro duplicado 409, login 200 com `Set-Cookie`, login inválido 401
- [ ] E2E: refresh emite novo par de cookies, refresh com token revogado/expirado retorna 401
- [ ] E2E: logout limpa cookies e revoga o refresh token
- [ ] E2E: rota protegida sem cookie retorna 401 (ISO-01)
- [ ] E2E: 6ª tentativa de login em 15min retorna 429
- [ ] Gate check passa: `uv run pytest tests/unit tests/integration -q`
- [ ] Test count: 8+ testes e2e

**Tests**: integration
**Gate**: full

**Commit**: `feat(api): add auth router and get_current_user dependency`

---

### T10: Project router

**What**: Endpoints `POST/GET /projects`, `PATCH/DELETE /projects/{id}`.
**Where**: `app/api/routers/projects.py`
**Depends on**: T9, T7
**Reuses**: `ProjectService` (T9), `get_current_user` (T7)
**Requirement**: PROJ-01..04, ISO-02

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] E2E: criar, listar (só os do usuário), renomear cobertos
- [ ] E2E: delete de projeto com tarefas retorna 409; delete sem tarefas retorna 204
- [ ] E2E: usuário B recebe 404 ao acessar/editar/deletar projeto de A (ISO-02)
- [ ] Gate check passa: `uv run pytest tests/unit tests/integration -q`
- [ ] Test count: 8+ testes e2e

**Tests**: integration
**Gate**: full

**Commit**: `feat(api): add projects router`

---

### T13: Task router

**What**: Endpoints `POST/GET /projects/{id}/tasks`, `PATCH/DELETE /tasks/{id}`.
**Where**: `app/api/routers/tasks.py`
**Depends on**: T12, T10
**Reuses**: `TaskService` (T12), `get_current_user` (T7), padrão de ownership do `projects.py` (T10)
**Requirement**: TASK-01..04, STAT-01, TAG-01, TAG-02

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] E2E: criar só com título (201), sem título (422)
- [ ] E2E: editar cada campo via PATCH, listar por projeto
- [ ] E2E: todas as transições de status via API, incl. valor inválido (422)
- [ ] E2E: tags válidas aceitas, tag >20 chars rejeitada (422)
- [ ] E2E: usuário B recebe 404 ao acessar tarefa de projeto de A
- [ ] Gate check passa: `uv run pytest tests/unit tests/integration -q`
- [ ] Test count: 12+ testes e2e

**Tests**: integration
**Gate**: full

**Commit**: `feat(api): add tasks router`

---

### T15: Attachment router + `AttachmentService`

**What**: Endpoints `POST /tasks/{id}/attachments`, `DELETE /tasks/{id}/attachments/{attachment_id}`.
**Where**: `app/api/routers/attachments.py`, `app/services/attachment_service.py`
**Depends on**: T14, T13
**Reuses**: `StorageBackend` (T14), `get_current_user` (T7), padrão de ownership de tarefa (T13)
**Requirement**: ATT-01..03

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] E2E: upload com sucesso retorna referência do anexo
- [ ] E2E: arquivo >10MB retorna 413 sem salvar
- [ ] E2E: falha do storage (mockada) retorna 502 sem afetar os demais dados da tarefa
- [ ] E2E: remoção de anexo remove do storage e da listagem
- [ ] Gate check passa: `uv run pytest tests/unit tests/integration -q`
- [ ] Test count: 6+ testes e2e

**Tests**: integration
**Gate**: full

**Commit**: `feat(api): add attachments router`

---

### T16: Wiring final (CORS, cookies, rate limiter, app assembly)

**What**: Montar todos os routers no `app/main.py`, configurar CORS restrito à origem do frontend com `credentials: true`, cookies `Secure`+`SameSite=Lax` em produção, `slowapi` global.
**Where**: `app/main.py`
**Depends on**: T7, T10, T13, T15
**Reuses**: todos os routers das fases anteriores
**Requirement**: n/a (integração final)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `uv run uvicorn app.main:app` sobe com todos os routers montados
- [ ] `GET /health` e `GET /docs` (OpenAPI) respondem 200
- [ ] CORS testado: origem do frontend permitida com credentials, outras origens bloqueadas
- [ ] Suíte completa passa: `uv run pytest -q`
- [ ] `uv run pip-audit` limpo

**Tests**: none (smoke test de wiring incluso no gate)
**Gate**: build

**Commit**: `chore(api): wire routers, CORS and rate limiter into app entrypoint`

---

### T17: Dockerfile multi-stage + usuário não-root

**What**: `Dockerfile` de produção com stage `builder` (uv sync) e stage `runtime` (slim, só `.venv`+código), rodando como usuário `appuser` não-root.
**Where**: `Dockerfile`, `.dockerignore`
**Depends on**: T16
**Reuses**: `uv.lock` (T1) como fonte de dependências do stage `builder`
**Requirement**: n/a (infra/deploy — pedido explícito do usuário)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `docker build` conclui com sucesso, gerando a imagem final a partir do stage `runtime`
- [ ] Stage `runtime` não contém `uv` nem toolchain de build (verificado, ex.: `docker run --rm <imagem> which uv` retorna vazio/erro)
- [ ] `docker run` sobe o container e `whoami` dentro dele retorna `appuser` (não `root`)
- [ ] Tentativa de escrever fora dos diretórios com `chown` explícito (ex.: `touch /usr/local/lib/...`) falha por permissão dentro do container
- [ ] `GET /health` responde 200 através do container publicado
- [ ] `.dockerignore` exclui `.venv/`, `.git/`, `.specs/`, `tests/` da build context

**Tests**: none (verificação via gate manual dos itens acima)
**Gate**: build

**Commit**: `build(docker): add multi-stage Dockerfile with non-root runtime user`

---

## Parallel Execution Map

```
Phase 1 (Sequential):
  T1 → T2 → T3

Phase 2 (Parallel):
  T1 complete, then:
    ├── T4  [P]
    └── T14 [P]

Phase 3 (Sequential — shared test DB):
  T3 complete, then:
    T5 → T8 → T11

Phase 4 (Parallel — unit tests, mocked repos):
  T4,T5,T8,T11,T14 complete, then:
    ├── T6  [P]
    ├── T9  [P]
    └── T12 [P]

Phase 5 (Sequential — shared test DB):
  T6,T9,T12 complete, then:
    T7 → T10 → T13 → T15

Phase 6 (Sequential):
  T7,T10,T13,T15 complete, then:
    T16

Phase 7 (Sequential):
  T16 complete, then:
    T17
```

**Parallelism constraint:** A task marked `[P]` must have ALL of these:
- No unfinished dependencies
- Required test type is parallel-safe (per the Parallelism Assessment above)
- No shared mutable state with other `[P]` tasks in the same phase

---

## Task Granularity Check

| Task | Scope | Status |
| --- | --- | --- |
| T1: Setup uv | 1 config/skeleton | ✅ Granular |
| T2: Engine + Alembic | 1 config | ✅ Granular |
| T3: Modelos + migration | 5 modelos coesos, 1 migration | ✅ Granular (coeso — mesma migration) |
| T4: Security utils | 1 arquivo, 2 classes coesas | ✅ Granular |
| T14: StorageBackend | 1 protocolo + 2 implementações coesas | ✅ Granular (coeso — mesma interface) |
| T5: User+RefreshToken repo | 2 repositories coesos (mesma vertical de auth) | ✅ Granular |
| T8: Project repo | 1 repository | ✅ Granular |
| T11: Task repo | 1 repository | ✅ Granular |
| T6: AuthService | 1 service | ✅ Granular |
| T9: ProjectService | 1 service | ✅ Granular |
| T12: TaskService | 1 service | ✅ Granular |
| T7: Auth router + dependency | 1 router + 1 dependency coesos (auth) | ✅ Granular |
| T10: Project router | 1 router | ✅ Granular |
| T13: Task router | 1 router | ✅ Granular |
| T15: Attachment router + service | 1 router + 1 service coesos (attachments) | ✅ Granular |
| T16: Wiring | 1 arquivo (main.py) | ✅ Granular |
| T17: Dockerfile multi-stage | 1 arquivo (Dockerfile) + 1 config (.dockerignore) coesos | ✅ Granular |

---

## Diagram-Definition Cross-Check

| Task | Depends On (task body) | Diagram Shows | Status |
| --- | --- | --- | --- |
| T1 | None | None | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T2 | T2 → T3 | ✅ Match |
| T4 | T1 | T1 → T4 | ✅ Match |
| T14 | T1 | T1 → T14 | ✅ Match |
| T5 | T3 | T3 → T5 | ✅ Match |
| T8 | T3 | T5 → T8 | ✅ Match (sequencial na fase, mesma origem T3) |
| T11 | T3 | T8 → T11 | ✅ Match (sequencial na fase, mesma origem T3) |
| T6 | T4, T5 | T4,T5,T8,T11,T14 → T6 | ✅ Match |
| T9 | T8 | T4,T5,T8,T11,T14 → T9 | ✅ Match |
| T12 | T11 | T4,T5,T8,T11,T14 → T12 | ✅ Match |
| T7 | T6 | T6 → T7 | ✅ Match |
| T10 | T9, T7 | T7 → T10 (e depende de T9, completo na fase anterior) | ✅ Match |
| T13 | T12, T10 | T10 → T13 (e depende de T12, completo na fase anterior) | ✅ Match |
| T15 | T14, T13 | T13 → T15 (e depende de T14, completo na fase 2) | ✅ Match |
| T16 | T7, T10, T13, T15 | T7,T10,T13,T15 → T16 | ✅ Match |
| T17 | T16 | T16 → T17 | ✅ Match |

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| --- | --- | --- | --- | --- |
| T1: Setup uv | config | none | none | ✅ OK |
| T2: Engine+Alembic | config | none | none | ✅ OK |
| T3: Modelos | entity | none | none | ✅ OK |
| T4: Security utils | core (pure) | unit | unit | ✅ OK |
| T14: StorageBackend | storage | unit | unit | ✅ OK |
| T5: User/RefreshToken repo | repository | integration | integration | ✅ OK |
| T8: Project repo | repository | integration | integration | ✅ OK |
| T11: Task repo | repository | integration | integration | ✅ OK |
| T6: AuthService | service | unit | unit | ✅ OK |
| T9: ProjectService | service | unit | unit | ✅ OK |
| T12: TaskService | service | unit | unit | ✅ OK |
| T7: Auth router | router (highest layer touched) | integration | integration | ✅ OK |
| T10: Project router | router | integration | integration | ✅ OK |
| T13: Task router | router | integration | integration | ✅ OK |
| T15: Attachment router+service | router (highest) | integration | integration | ✅ OK |
| T16: Wiring | config/entrypoint | none | none | ✅ OK |
| T17: Dockerfile | infra/build | none | none | ✅ OK |

Nenhuma violação — todas as tasks que criam camada com teste obrigatório incluem os testes na própria task (sem deferral).
