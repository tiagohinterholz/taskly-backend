# STATE

## Decisions

### AD-001
- **Decision**: Backend e frontend vivem em repositórios git separados (`backend/`, `frontend/`), cada um com seu próprio `.specs/`.
- **Reason**: Reflete o modelo de entrega do case (repositório GitHub por parte da stack) e mantém os dois lados desacoplados.
- **Trade-off**: Contrato de API precisa ser mantido em sincronia manualmente entre `backend/.specs/features/taskly-api/spec.md` e `frontend/.specs/features/taskly-ui/spec.md`.
- **Scope**: Todo o projeto Taskly.
- **Date**: 2026-07-23
- **Status**: active

### AD-002
- **Decision**: Backend em FastAPI (Python); frontend em React.
- **Reason**: Escolha do usuário por familiaridade e produtividade ("FastAPI... Python claro pra facilitar", "React... acho o mais tranquilo pra mim").
- **Trade-off**: Nenhum framework foi comparado formalmente; escolha é de conforto, não de benchmark técnico.
- **Scope**: Todo o projeto Taskly.
- **Date**: 2026-07-23
- **Status**: active

### AD-003
- **Decision**: Autenticação via JWT (access token de curta duração + refresh token), ambos entregues como cookies httpOnly. Frontend não manipula tokens diretamente em JS.
- **Reason**: Usuário confirmou explicitamente; evita exposição de token a XSS via localStorage.
- **Trade-off**: Exige configuração de CORS com credentials e atenção a CSRF (mitigar com SameSite cookie + CSRF token em mutações, a detalhar no Design).
- **Scope**: Backend (emissão) + Frontend (consumo transparente via cookie).
- **Date**: 2026-07-23
- **Status**: active

### AD-004
- **Decision**: Storage de anexos abstraído atrás de uma interface (`StorageBackend`); implementação local (filesystem) em desenvolvimento, S3 em produção.
- **Reason**: Usuário confirmou que S3 só entra "depois no deploy" — precisa de um adapter local para não bloquear o dev sem AWS.
- **Trade-off**: Duas implementações para manter em paridade de comportamento (erros, limites de tamanho).
- **Scope**: Backend.
- **Date**: 2026-07-23
- **Status**: active

### AD-005
- **Decision**: Arquitetura em camadas — routers → services → repositories → SQLAlchemy 2.0 async (`asyncpg`) → Postgres, com Alembic para migrations.
- **Reason**: Escolhida pelo usuário entre 3 opções apresentadas (layered / SQLModel / fat routes); melhor equilíbrio entre separação de responsabilidades (critério de avaliação do case) e velocidade para 3 dias.
- **Trade-off**: Mais arquivos/boilerplate que SQLModel (schemas Pydantic separados dos modelos ORM).
- **Scope**: Backend.
- **Date**: 2026-07-23
- **Status**: active

### AD-006
- **Decision**: Refresh tokens persistidos no banco (hash), com rotação a cada `/auth/refresh` e revogação no `/auth/logout`. Access token continua stateless (JWT curto, sem lookup em banco).
- **Reason**: Permite invalidação real de sessão no logout; JWT stateless puro não permite revogar antes de expirar.
- **Trade-off**: Tabela extra (`refresh_tokens`) e uma escrita a cada refresh.
- **Scope**: Backend.
- **Date**: 2026-07-23
- **Status**: active

### AD-007
- **Decision**: Tags armazenadas como coluna `ARRAY(String(20))` na própria tabela `tasks`, sem tabela `tags` separada.
- **Reason**: Tags são texto livre por tarefa; não há requisito de listar/reusar tags entre tarefas no escopo do case.
- **Trade-off**: Sem autocomplete/reuso de tags entre tarefas sem uma query agregada futura.
- **Scope**: Backend.
- **Date**: 2026-07-23
- **Status**: active

### AD-008
- **Decision**: Projeto Python gerenciado por `uv` (Astral) — `pyproject.toml` + `uv.lock`, sem pip/venv/poetry manual.
- **Reason**: Pedido explícito do usuário.
- **Trade-off**: Ferramenta mais nova que pip/poetry; time precisa estar confortável com o CLI do `uv` (`uv add`, `uv sync`, `uv run`).
- **Scope**: Backend.
- **Date**: 2026-07-23
- **Status**: active

### AD-009
- **Decision**: Prática de segurança de dependências — versões fixadas (sem `^`/`~`) no `pyproject.toml`, `uv.lock` versionado, instalação sempre via `uv sync --locked`, `uv run pip-audit` na task de setup/CI. Qualquer dependência nova (inclusive sugerida por IA) é revisada manualmente antes de adicionada.
- **Reason**: Mitigar risco de supply-chain attack (pacotes PyPI comprometidos) — preocupação explícita do usuário, casos recentes de pacotes populares comprometidos no ecossistema.
- **Trade-off**: Upgrades de dependência exigem passo manual (`uv lock --upgrade-package`) em vez de range automático.
- **Scope**: Backend.
- **Date**: 2026-07-23
- **Status**: active

### AD-010
- **Decision**: `Dockerfile` multi-stage — stage `builder` roda `uv sync --locked --no-dev` para materializar `.venv`; stage `runtime` (slim) copia só `.venv` + código da app, sem `uv`/toolchain de build. Usuário de aplicação não-root (`appuser`) no stage final, com `chown` restrito ao código e à pasta de anexos locais; `USER appuser` antes do `CMD`.
- **Reason**: Pedido explícito do usuário — reduzir tamanho da imagem final e aplicar hardening básico (processo comprometido não ganha permissão de escrita no filesystem da imagem).
- **Trade-off**: Dockerfile mais complexo que um build single-stage; qualquer novo diretório que precise de escrita em runtime precisa de `chown` explícito.
- **Scope**: Backend.
- **Date**: 2026-07-23
- **Status**: active

### AD-011
- **Decision**: Repositories fazem `flush()` mas nunca `commit()` — a fronteira da transação pertence sempre a quem chama (camada de service).
- **Reason**: Permite que um service componha múltiplas operações de repository (ex.: deletar tarefa + seus anexos) numa única transação atômica, decidindo o commit/rollback no fim, em vez de cada repository commitar isoladamente.
- **Trade-off**: Todo service precisa lembrar de commitar explicitamente ao final; repositories sozinhos não persistem nada.
- **Scope**: Backend (services que ainda serão implementados: T6, T9, T12 devem seguir essa convenção).
- **Date**: 2026-07-23
- **Status**: active

## Handoff

- **Feature**: `backend/.specs/features/taskly-api`
- **Phase / Task**: Execute em andamento — Fases 1, 2 e 3 concluídas (T1, T2, T3, T4, T14, T5, T8, T11), Fase 4 prestes a ser disparada (T6, T9, T12 em paralelo — services)
- **Completed**: spec.md, design.md, tasks.md; T1 (`48b9f28`), T2 (`619952b`), T3 (`8ff4b88`), docs (`7e4d50b`), T4 (`ae3dc50`), T14 (`996d2ae`), T5 (`d8d8228`), T8 (`bafb7bc`), T11 (`61fe594`) — 36 testes passando (13 unit + 23 integration)
- **In-progress**: nenhuma task em execução no momento; prestes a disparar Fase 4
- **Next step**: Disparar sub-agente da Fase 4 (`AuthService` T6, `ProjectService` T9, `TaskService` T12 — todos unit test, repository mockado, podem rodar em paralelo dentro do mesmo worker)
- **Blockers**: none
- **Uncommitted files**: `.specs/STATE.md` (esta atualização, a ser commitada agora)
- **Branch**: master
- **Notas de ambiente**: Postgres de dev local em `localhost:5433`, container `backend-postgres-1` healthy, mantido entre fases. `bcrypt==4.0.1` fixado por incompatibilidade com o backend bcrypt do `passlib`. `pytest-asyncio==1.4.0` adicionado (já previsto em design.md) com `asyncio_mode`/`asyncio_default_fixture_loop_scope`/`asyncio_default_test_loop_scope = "session"` em `pyproject.toml`, e `tests/conftest.py` carrega `.env` antes de `app.core.db` ser importado. Fixture `db_session` em `tests/integration/conftest.py` (truncate-all-tables após cada teste) — reutilizar em T7/T10/T13/T15.
