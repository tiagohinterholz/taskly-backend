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

### AD-012
- **Decision**: Verificação de ownership (o recurso pertence ao usuário autenticado) acontece na camada de **service** via lookups escopados por `user_id`/`project_id` (`ProjectRepository.get_for_user`, `TaskRepository.get_for_project`), levantando exceções de domínio (`ProjectNotFoundError`, `TaskNotFoundError`) — nunca deixada implícita ou reimplementada em cada router.
- **Reason**: Revisão pós-Fase 4 encontrou que `ProjectService.rename`/`delete` recebiam `user_id` sem usá-lo (parâmetro morto) e `TaskService` nem recebia contexto de ownership — uma brecha de IDOR real (qualquer usuário autenticado podia mutar recurso de outro usuário sabendo o UUID). Corrigido via T18 antes da Fase 5 (routers), alinhando com o que `design.md` já dizia na Error Handling Strategy.
- **Trade-off**: `TaskService.update`/`delete` ganharam `project_id` como parâmetro obrigatório (mudança de assinatura pós-Fase-4, sem impacto externo pois routers ainda não existiam).
- **Scope**: Backend (routers T10/T13 devem usar essas checagens, não reimplementar ownership por conta própria).
- **Date**: 2026-07-23
- **Status**: active

## Handoff

- **Feature**: `backend/.specs/features/taskly-api`
- **Phase / Task**: Execute em andamento — Fases 1-5 concluídas (todos os routers); Fase 6 (T16, wiring final) prestes a ser disparada
- **Completed**: spec.md, design.md, tasks.md (18 tasks); commits até `c89b501` (T15) — 150 testes passando
- **In-progress**: nenhuma task em execução; prestes a disparar Fase 6
- **Next step**: Disparar agente para T16 (montar todos os routers em `app/main.py`, CORS restrito à origem do frontend com credentials, cookies Secure+SameSite=Lax em produção, rate limiter global) — depois Fase 7 (T17 Dockerfile)
- **Blockers**: none
- **Uncommitted files**: nenhum
- **Branch**: master
- **Notas de ambiente**: Postgres de dev local em `localhost:5433`, container `backend-postgres-1` healthy. `bcrypt==4.0.1` fixado. `httpx` + `python-multipart` adicionados como deps (T7/T15). N+1 de anexos resolvido via `AttachmentRepository.list_for_tasks` (batch, com teste de regressão de contagem de query) — reutilizar esse padrão se novas listagens agregadas surgirem. `AuthService` reconstruído por request compartilha o rate-limit dict via um dict no nível do módulo do router — se T16 mudar a forma como `AuthService` é instanciado (ex.: DI via `Depends`), preservar esse compartilhamento pra não quebrar AUTH-05 (429).
