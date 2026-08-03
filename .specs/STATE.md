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

### AD-017
- **Decision**: `POSTGRES_PASSWORD` lido de `${POSTGRES_PASSWORD}` no `docker-compose.yml` (via `.env`, com fallback `taskly` pro dev local), nunca mais hardcoded direto no compose file.
- **Reason**: Incidente real em produção — a senha só tinha sido trocada editando `docker-compose.yml` direto na EC2 (arquivo rastreado pelo git). O deploy automático (`git reset --hard origin/master`) desfez essa edição a cada push, revertendo pro placeholder antigo — mas o Postgres já tinha inicializado o volume com a senha nova de verdade (ignora `POSTGRES_PASSWORD` quando o volume já existe), então a API passou a falhar `InvalidPasswordError` em toda conexão. Dados nunca foram perdidos, só ficaram inacessíveis pelo mismatch de credencial.
- **Trade-off**: Nenhum — só corrige uma fragilidade real (qualquer arquivo git-tracked que precise de valor específico de servidor é incompatível com `git reset --hard` em deploy automatizado).
- **Scope**: Backend (infra/deploy) — regra geral pra lembrar: segredo de servidor nunca em arquivo rastreado, sempre em `.env`.
- **Date**: 2026-07-26
- **Status**: active

### AD-018
- **Decision**: Autorização de projeto ampliada via grupo (`groups-rbac`) é **aditiva**: `ProjectRepository.get_for_user`/`list_for_user` (estritos, só `user_id`) continuam existindo intactos e são os únicos usados por `ProjectService.rename`/`delete`. Dois métodos novos — `get_accessible_for_user`/`list_accessible_for_user` (`user_id == dono` OU membro do `group_id` do projeto) — cobrem leitura/listagem/tarefas/anexos, plugados num único ponto de extensão (`_get_owned_project_id` em `tasks.py`, renomeado `_get_accessible_project_id`, já reaproveitado por `attachments.py`).
- **Reason**: Evita que a introdução de grupos altere silenciosamente o comportamento de renomear/excluir projeto (que a spec nunca pediu para abrir a Membro) — mantém o isolamento do v1 intacto pra quem nunca usa grupos, e concentra a extensão de acesso num só lugar em vez de espalhar checagens por múltiplos routers.
- **Trade-off**: Dois pares de métodos (estrito vs. ampliado) em `ProjectRepository` em vez de um só — mais explícito sobre qual checagem cada operação usa, ao custo de mais uma assinatura de método pra manter.
- **Scope**: Backend (`app/repositories/project_repository.py`, `app/api/routers/tasks.py`, `app/api/routers/attachments.py`).
- **Date**: 2026-08-02
- **Status**: active

### AD-019
- **Decision**: `generate_opaque_token()`/`hash_token()` extraídos para `app/core/security.py`; `AuthService` (refresh token, v1) e `GroupService` (convite de grupo, v2) usam as mesmas funções em vez de duplicar `secrets.token_urlsafe(32)` + `hashlib.sha256(...).hexdigest()`.
- **Reason**: Duplicação real identificada durante o Design de `groups-rbac` — mesmo racional da extração de `BaseRepository` (AD-014): reaproveitar em vez de copiar um padrão de segurança que precisa ficar consistente nos dois lugares.
- **Trade-off**: Nenhum — extração pura, sem mudança de comportamento no fluxo de refresh token existente (mesmos parâmetros, mesmo algoritmo).
- **Scope**: Backend (`app/core/security.py`, `app/services/auth_service.py`, `app/services/group_service.py`).
- **Date**: 2026-08-02
- **Status**: active

### AD-020
- **Decision**: `CreatedAtMixin`/`TimestampMixin` (`app/models/base.py`) substituem os campos `created_at`/`updated_at` duplicados inline em todos os 8 models. Convenção: mixin sempre listado ANTES de `Base` na herança (`class Model(TimestampMixin, Base)`), seguindo a própria documentação do SQLAlchemy 2.0 pra ordem de MRO em mixins declarativos.
- **Reason**: Usuário apontou a duplicação diretamente ("as classes elas tão repetindo created_at updated_at... abstrai isso numa classe pra ser herdada") ao ver os 3 models novos de `groups-rbac` repetirem o mesmo padrão dos 5 já existentes — mesmo racional de `BaseRepository` (AD-014), agora aplicado à camada de model.
- **Trade-off**: Nenhum — refatoração pura de código Python, sem mudança de nome/tipo/default de coluna, portanto **sem migration necessária**.
- **Scope**: Backend (todos os models). Qualquer model futuro com timestamp deve herdar de um dos dois mixins em vez de declarar as colunas inline.
- **Date**: 2026-08-02
- **Status**: active

### AD-021
- **Decision**: Paginação real (não só "watch out") em toda listagem da API, v1 incluído — `GET /projects` e `GET /projects/{id}/tasks` (breaking change) e todo endpoint de listagem novo de `groups-rbac`. Padrão único: `PaginationParams` (dependency FastAPI: `limit` 1–100, default 50; `offset` ≥0, default 0) + envelope de resposta genérico `Page[T]` (`{"items": [...], "total": N, "limit": L, "offset": O}`). Filtro por campo quando fizer sentido pra entidade — `status` opcional em `GET .../tasks` (único filtro óbvio hoje); projetos/grupos sem filtro extra no MVP.
- **Reason**: Usuário identificou a lacuna (já registrada como gap conhecido em `../resumo.local.md`) e pediu paginação real, incluindo retrofit do v1, não só documentar como pendência.
- **Trade-off**: Breaking change no contrato de `GET /projects`/`GET .../tasks` (array vira envelope) — frontend precisa acompanhar na mesma leva (usuário confirmou deploy conjunto, "eu subo tudo junto sem problema"). `groups-rbac` ainda em Execute (Fase 2 em diante) — os endpoints de listagem novos (`GET /groups`, `/members`, `/invites`) nascem já usando este padrão, sem retrabalho.
- **Scope**: Backend (`app/api/pagination.py` novo, `ProjectRepository`/`TaskRepository`, routers de projects/tasks, e os routers de `groups-rbac` ainda não implementados) + Frontend (hooks de projetos/tarefas).
- **Date**: 2026-08-02
- **Status**: active

### AD-022
- **Decision**: `ProjectOut` ganhou `group_id: uuid.UUID | None`; `GET /projects` ganhou filtro opcional `?group_id=`; `MemberOut` ganhou `email: str` (via join com `User`, já que um `user_id` cru não é uma identidade utilizável numa lista de membros).
- **Reason**: Levantamento de API feito no Design de `groups-ui` (frontend) achou 3 gaps de dado reais: nada indicava, olhando `GET /projects`, se um projeto era de grupo (bloqueava o badge de grupo na sidebar); não existia forma de listar os projetos de um grupo específico (resolvido reaproveitando `GET /projects` com filtro, em vez de criar rota nova); `MemberOut` não tinha e-mail, tornando a lista de membros ilegível pra um humano.
- **Trade-off**: Nenhum — todas as 3 mudanças são aditivas (campo novo, filtro opcional, join adicional), nenhum contrato existente quebra. `group_id` na condição do filtro é sempre combinado com (nunca substitui) a checagem de acesso (AD-018) — não abre brecha de IDOR.
- **Scope**: Backend (`app/api/routers/projects.py`, `app/api/routers/groups.py`, `app/repositories/project_repository.py`, `app/repositories/group_repository.py`, `app/services/project_service.py`, `app/services/group_service.py`).
- **Date**: 2026-08-02
- **Status**: active

## Handoff

- **Feature**: `groups-rbac` (backend) — ✅ **VERIFIED (PASS)**, todos os gaps do Verifier fechados, 345 testes (incl. AD-022's 3 extensões pós-Verifier pra habilitar `groups-ui`), `pip-audit` limpo. `groups-ui` (frontend, repo separado) — ✅ **VERIFIED (PASS)** também, ver `frontend/.specs/STATE.md`. Backend **ainda não commitado pro repo remoto** (usuário decidiu subir tudo junto com o frontend numa leva só, já que a avaliação do case nem olhou a v1 ainda).
- **Phase / Task**: Ambas as features (`groups-rbac` backend + `groups-ui` frontend) encerradas e verificadas. Usuário testou manualmente em ambiente local (Docker + `npm run dev`) e confirmou o fluxo de criar grupo/projeto funcionando.
- **Completed**: `groups-rbac` spec.md/design.md/tasks.md/validation.md; `groups-ui` (frontend) spec.md/design.md/tasks.md/validation.md — ambos PASS.
- **In-progress**: nenhuma.
- **Next step**: usuário vai, numa sessão futura, migrar pra "uma versão funcional de tudo com serviços de integração" (escopo ainda não especificado). Antes disso, decidir quando fazer o push conjunto backend+frontend pro remoto e redeploy na EC2 (nenhum dos dois foi pra produção ainda com esse código).
- **Blockers**: none.
- **Uncommitted files**: none (working tree limpo, tudo commitado localmente).
- **Branch**: master.
- **Notas de ambiente**: `groups-rbac` é puramente aditivo sobre o v1 (AD-018) — `ProjectRepository.get_for_user`/`get_accessible_for_user` coexistem, o primeiro estrito (rename/delete), o segundo ampliado por grupo (leitura/tarefas/anexos). Core proof test: `tests/integration/api/test_tasks_router.py::TestGroupMemberTaskAccess`. Wiring smoke check: `tests/integration/api/test_app_wiring.py::TestHealthAndDocs::test_openapi_json_lists_groups_router_routes`. Postgres de dev local em `localhost:5433`.
