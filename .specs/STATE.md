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

### AD-013
- **Decision**: Todas as rotas de tarefa/anexo aninhadas sob `/projects/{project_id}/tasks/{task_id}[/attachments/...]` — sem exceção. A rota flat `PATCH/DELETE /tasks/{id}` foi eliminada.
- **Reason**: Revisão de código pelo usuário pós-verificação apontou inconsistência (criar/listar tarefa era aninhado, editar/deletar era flat), o que forçava um lookup não-escopado (`TaskRepository.get_by_id`) seguido de checagem de ownership — mais complexo que necessário e a própria causa da complexidade extra introduzida no T18. Com `project_id` sempre na URL, o router verifica ownership do projeto uma vez só, no topo do handler.
- **Trade-off**: Breaking change de contrato de API (`refactor(api)!` com `BREAKING CHANGE:` no commit) — como o frontend ainda não tinha iniciado o Execute, o custo foi mínimo (só atualizar `design.md` do frontend antes de começar).
- **Scope**: Backend (rotas) + Frontend (contrato consumido, `design.md` já atualizado).
- **Date**: 2026-07-24
- **Status**: active

### AD-014
- **Decision**: `BaseRepository[Model]` genérica (`app/repositories/base.py`) com `__init__`/`get_by_id`/`delete`; todos os 6 repositories herdam dela, mantendo apenas métodos entidade-específicos (`create`, `get_for_user`, `list_for_project`, etc.) como overrides.
- **Reason**: Duplicação real e evidenciada (mesmo `__init__` em 6 arquivos, mesmo padrão `get_by_id`/`delete` em 3 deles) — apontada em revisão de código.
- **Trade-off**: Uma camada de indireção a mais (generics) em troca de ~6 blocos duplicados removidos; métodos genéricos precisam ser lidos junto com a classe base pra entender o contrato completo de cada repository.
- **Scope**: Backend (qualquer repository futuro deve herdar de `BaseRepository` por padrão, só implementando o que for genuinamente específico).
- **Date**: 2026-07-24
- **Status**: active

### AD-015
- **Decision**: Container roda `alembic upgrade head` automaticamente via `entrypoint.sh` antes de subir o `uvicorn`; falha de migration aborta o start do container (não sobe API contra schema desatualizado).
- **Reason**: Gap real apontado pelo usuário — o Dockerfile copiava os arquivos do Alembic mas nunca executava a migration; um deploy novo subiria a API contra um banco vazio.
- **Trade-off**: Nenhum runtime extra além do próprio tempo de migration no start; em clusters com múltiplas réplicas subindo ao mesmo tempo, migrations concorrentes poderiam colidir (não é o caso do deploy planejado — EC2 de instância única) — documentar como ponto de atenção se a topologia mudar.
- **Scope**: Backend (deploy/infra).
- **Date**: 2026-07-24
- **Status**: active

### AD-016
- **Decision**: `AttachmentOut.url` sempre aponta pra um endpoint próprio da API (`GET .../attachments/{id}/download`, protegido por ownership), nunca uma URL de storage crua. O endpoint decide internamente: redirect (307) pra presigned URL se o backend for S3, ou proxy do conteúdo (`StorageBackend.read`) se for local.
- **Reason**: Gap real encontrado durante a integração do frontend (T10) — `ATT-01` exige retornar "a URL/referência do anexo", mas a implementação original (T15) só devolvia `storage_key`, um identificador interno não-navegável. Isso passou pelos dois rounds do Verifier porque nenhum teste checava se a "referência" era de fato dereferenciável.
- **Trade-off**: Endpoint de download precisa lidar com dois caminhos (redirect vs. proxy) em vez de um `url` estático simples; para local, o proxy consome banda do próprio servidor da API (aceitável no escopo do case).
- **Scope**: Backend (contrato de resposta de anexos) + Frontend (consome a URL real em vez do workaround client-side de preview por sessão).
- **Date**: 2026-07-24
- **Status**: active

## Handoff

- **Feature**: `backend/.specs/features/taskly-api` — ✅ **VERIFIED (PASS)** duas vezes; T19 (fix de URL de anexo) em andamento como correção pós-verificação adicional
- **Phase / Task**: Execute + Verify + revisão manual do usuário + re-verificação, todas concluídas; T19 disparada pra fechar o gap de ATT-01 encontrado na integração com o frontend
- **Completed**: spec.md, design.md, tasks.md, validation.md (PASS, commit `8a75c02`), LESSONS.md/lessons.json (7 lições candidatas), README.md; 182 testes passando (antes de T19); `docker build` verificado
- **In-progress**: T19 (endpoint de download de anexo + `get_url`/`read` no `StorageBackend`)
- **Next step**: Depois de T19 fechar (gate verde), atualizar o `AttachmentUploader.tsx` do frontend pra consumir a URL real em vez do workaround de `URL.createObjectURL` só-sessão. Considerar rodar o Verifier mais uma vez focado em ATT-01 dado que é uma mudança pós-verificação em área nova (endpoint novo).
- **Blockers**: none
- **Uncommitted files**: `.specs/features/taskly-api/tasks.md`, `.specs/STATE.md` (T19 documentada nesta rodada)
- **Branch**: master
- **Gaps Minor não bloqueantes ainda abertos** (nenhum é regressão, nenhum bloqueia): (1) boundary de nome de projeto (1-100 chars) sem teste explícito — lição L-006; (2) cenário "project_id do atacante na URL + task_id de outro projeto" só coberto em teste de repository, não em teste e2e do router — lição L-007; (3) `AttachmentOut` sem URL utilizável — lição a registrar após T19 fechar, sobre testar se uma "referência" é de fato dereferenciável quando o AC pede URL.
- **Notas de ambiente**: Postgres de dev local em `localhost:5433`, container `backend-postgres-1` healthy. `bcrypt==4.0.1` fixado. `python-multipart==0.0.31`. N+1 de anexos resolvido via `AttachmentRepository.list_for_tasks` (batch). `Dockerfile` multi-stage + `entrypoint.sh` (migração automática) prontos. Rotas de task/anexo 100% aninhadas sob `/projects/{id}/tasks/{id}[/attachments/...]` (AD-013), ownership verificado uma vez por request via `ProjectRepository.get_for_user` + `TaskRepository.get_for_project` — confirmado sem regressão de IDOR pela re-verificação.
