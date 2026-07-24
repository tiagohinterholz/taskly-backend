# Taskly API Specification

## Problem Statement

Este é o case técnico de seleção da UEX Startup Studio (vaga Desenvolvedor Fullstack): construir a API do Taskly, um sistema de gestão de tarefas pessoais. O backend deve prover autenticação própria, gestão de projetos e tarefas com todos os campos exigidos, e servir como contrato REST estável para o frontend (repositório separado, `frontend/`).

## Goals

- [ ] Autenticação própria (e-mail/senha) com sessão persistente via cookie, sem depender de OAuth
- [ ] Isolamento total de dados por usuário (cada um só acessa seus próprios projetos/tarefas)
- [ ] CRUD completo de projetos e tarefas com todos os campos do case (título, descrição curta, descrição completa, prazo, tags, anexos, status)
- [ ] Storage de anexos desacoplado via abstração (local em dev, S3 em produção)
- [ ] Documentação de API automática e sempre sincronizada com o código (OpenAPI/Swagger)
- [ ] Imagem de container mínima e sem privilégio de escrita desnecessário (hardening básico de deploy)

## Out of Scope

Explicitamente excluído. Documentado para prevenir scope creep.

| Feature                                   | Reason                                                                 |
| ------------------------------------------ | ----------------------------------------------------------------------- |
| OAuth / login social (Google, Microsoft)  | Case exige auth própria explicitamente                                |
| Colaboração multi-usuário / times / projetos compartilhados | Case não menciona; escopo é gestão pessoal, um usuário só vê os próprios dados |
| Notificações (e-mail/push) de prazo       | Não mencionado no case                                                |
| Busca/filtro avançado de tarefas          | Não é requisito mínimo; candidato a feature extra futura              |
| Exclusão de conta de usuário              | Não mencionado no case                                                |
| Múltiplos storages simultâneos / migração de anexos | Fora do escopo do case; abstração cobre troca dev↔prod, não migração de dados |

---

## Assumptions & Open Questions

Every ambiguity is resolved or recorded here — nothing is left silently unclear.

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Storage de anexos | Interface `StorageBackend` abstrata; implementação local (filesystem) em dev, S3 em produção | Usuário confirmou S3 "depois no deploy" — precisa de um adapter local para dev sem depender de AWS | n (default do agente) |
| Tags | Texto livre, até 20 caracteres cada, múltiplas por tarefa | Confirmado pelo usuário | y |
| Sessão | JWT (access token curto) + refresh token, ambos em cookies httpOnly | Confirmado pelo usuário | y |
| Escopo de dados | Usuário só acessa seus próprios projetos/tarefas; sem compartilhamento | Confirmado pelo usuário | y |
| Campos obrigatórios da tarefa | Apenas título; demais campos opcionais, editáveis depois | Confirmado pelo usuário | y |
| Delete de projeto com tarefas | Bloqueado (409) até o usuário remover as tarefas | Confirmado pelo usuário | y |
| Transições de status | Livres entre os 4 estados, sem ordem obrigatória | Case diz "atualizável a qualquer momento" | y |
| Rate limiting em login | Bloqueio temporário após N tentativas falhas por e-mail/IP | Dimensão "auth boundaries" exige alguma proteção contra brute-force; case não especifica número exato | n (default do agente — N=5 tentativas / 15min, ajustável) |
| Observabilidade | Log estruturado de ações-chave (criação de tarefa, mudança de status, login) | Critério de avaliação menciona "leitura de logs, métricas de produto"; mínimo viável sem virar projeto de observability | n (default do agente) |
| Tamanho máximo de anexo | 10MB por arquivo | Não especificado no case; limite de segurança razoável para evitar abuso | n (default do agente) |

**Open questions:** none — all resolved or logged above.

---

## User Stories

### P1: Autenticação própria ⭐ MVP

**User Story**: Como usuário, quero criar minha conta com e-mail e senha e depois logar, para acessar meus próprios projetos e tarefas com segurança.

**Why P1**: Sem autenticação não há como isolar dados por usuário — é pré-requisito de todas as demais stories.

**Acceptance Criteria**:

1. WHEN um visitante envia e-mail válido e único + senha (mín. 8 caracteres) para `POST /auth/register` THEN o sistema SHALL criar o usuário com senha hasheada (bcrypt/argon2) e retornar 201.
2. WHEN um visitante tenta registrar com e-mail já cadastrado THEN o sistema SHALL retornar 409 sem criar duplicata.
3. WHEN um usuário envia credenciais corretas para `POST /auth/login` THEN o sistema SHALL emitir access token (JWT, curta duração) e refresh token, ambos como cookies httpOnly, e retornar 200.
4. WHEN um usuário envia credenciais inválidas para `POST /auth/login` THEN o sistema SHALL retornar 401 sem indicar se o e-mail existe (evitar user enumeration).
5. WHEN o access token expira e o refresh token ainda é válido THEN `POST /auth/refresh` SHALL emitir novo access token sem exigir novo login.
6. WHEN um usuário chama `POST /auth/logout` THEN o sistema SHALL invalidar/limpar os cookies de sessão.
7. WHEN mais de 5 tentativas de login falham para o mesmo e-mail/IP em 15 minutos THEN o sistema SHALL retornar 429 para novas tentativas até a janela expirar.

**Independent Test**: registrar → logar → reenviar cookie em nova requisição (simula reabrir navegador) → acessar endpoint protegido com sucesso → logout → confirmar 401 no endpoint protegido.

---

### P1: Isolamento e proteção de rotas ⭐ MVP

**User Story**: Como usuário autenticado, quero que apenas eu acesse meus projetos e tarefas, para que meus dados fiquem privados.

**Why P1**: Requisito de segurança básico; sem isso o sistema não é utilizável por múltiplos usuários reais.

**Acceptance Criteria**:

1. WHEN uma requisição a qualquer endpoint de projeto/tarefa não possui sessão válida THEN o sistema SHALL retornar 401.
2. WHEN um usuário autenticado tenta acessar, editar ou deletar projeto/tarefa de outro usuário THEN o sistema SHALL retornar 404 (nunca 403 — não revelar existência do recurso).

**Independent Test**: criar usuários A e B, cada um com um projeto; confirmar que B recebe 404 ao tentar `GET /projects/{id_do_projeto_de_A}`.

---

### P1: Projetos ⭐ MVP

**User Story**: Como usuário autenticado, quero criar, listar e renomear meus projetos, para organizar meu trabalho em contextos separados.

**Why P1**: Estrutura base sobre a qual as tarefas existem; requisito explícito do case.

**Acceptance Criteria**:

1. WHEN um usuário envia nome (obrigatório, 1–100 caracteres) para `POST /projects` THEN o sistema SHALL criar o projeto vinculado a ele e retornar 201.
2. WHEN um usuário chama `GET /projects` THEN o sistema SHALL retornar somente os projetos que pertencem a ele.
3. WHEN um usuário envia novo nome para `PATCH /projects/{id}` THEN o sistema SHALL atualizar o nome do projeto.
4. WHEN um usuário tenta `DELETE /projects/{id}` de um projeto com tarefas THEN o sistema SHALL retornar 409 sem deletar.
5. WHEN um usuário deleta um projeto sem tarefas THEN o sistema SHALL remover o projeto e retornar 204.

**Independent Test**: criar projeto → listar → renomear → criar tarefa nele → tentar deletar (falha 409) → deletar a tarefa → deletar o projeto (sucesso 204).

---

### P1: Tarefas — CRUD e campos ⭐ MVP

**User Story**: Como usuário autenticado, quero criar e editar tarefas dentro de um projeto com título, descrições, prazo e tags, para registrar todo o contexto do meu trabalho.

**Why P1**: Núcleo funcional do produto; todos os campos são requisito explícito do case.

**Acceptance Criteria**:

1. WHEN um usuário envia título (1–200 caracteres, único campo obrigatório) para `POST /projects/{id}/tasks` THEN o sistema SHALL criar a tarefa com status inicial "Não iniciada" e demais campos vazios/nulos se omitidos.
2. WHEN um usuário envia título vazio ou ausente THEN o sistema SHALL retornar 422 sem criar a tarefa.
3. WHEN um usuário atualiza qualquer campo (título, descrição curta, descrição completa, prazo, tags, status) via `PATCH /projects/{project_id}/tasks/{id}` THEN o sistema SHALL persistir a alteração e retornar o recurso atualizado.
4. WHEN um usuário chama `GET /projects/{id}/tasks` THEN o sistema SHALL retornar todas as tarefas do projeto pertencentes a ele, com todos os campos, suficiente para renderizar lista ou kanban.
5. WHEN um usuário deleta uma tarefa THEN o sistema SHALL remover a tarefa e seus anexos associados.
6. WHEN um usuário envia prazo em formato inválido THEN o sistema SHALL retornar 422 com mensagem de validação.

**Independent Test**: criar tarefa só com título → editar todos os demais campos individualmente → confirmar persistência via `GET`.

---

### P1: Status da tarefa ⭐ MVP

**User Story**: Como usuário autenticado, quero mudar o status da tarefa livremente entre os 4 estados, para refletir o progresso real do meu trabalho.

**Why P1**: Requisito explícito do case; base para a visão Kanban do frontend.

**Acceptance Criteria**:

1. WHEN um usuário envia um novo status (um de: `not_started`, `in_progress`, `done`, `cancelled`) via `PATCH /projects/{project_id}/tasks/{id}` THEN o sistema SHALL aceitar a transição para qualquer um dos 4 estados, sem restrição de ordem.
2. WHEN um usuário envia um valor de status fora dos 4 permitidos THEN o sistema SHALL retornar 422.

**Independent Test**: mover uma tarefa por todas as combinações de status via API, incluindo "para trás" (`done` → `not_started`).

---

### P2: Tags

**User Story**: Como usuário autenticado, quero adicionar tags livres às tarefas, para organizar e filtrar visualmente meu trabalho.

**Why P2**: Enriquece a organização mas o produto funciona sem — não bloqueia o fluxo core.

**Acceptance Criteria**:

1. WHEN um usuário envia uma lista de tags (texto livre, cada uma até 20 caracteres) THEN o sistema SHALL salvar as tags associadas à tarefa.
2. WHEN um usuário envia uma tag com mais de 20 caracteres THEN o sistema SHALL retornar 422 indicando qual tag excedeu o limite.

**Independent Test**: adicionar 3 tags válidas → tentar adicionar uma com 21 caracteres → confirmar rejeição isolada (as 3 válidas permanecem).

---

### P2: Anexos

**User Story**: Como usuário autenticado, quero anexar arquivos/fotos às tarefas, para guardar contexto visual/documental.

**Why P2**: Requisito do case, mas não bloqueia o fluxo básico de gestão de tarefas.

**Acceptance Criteria**:

1. WHEN um usuário envia um arquivo (≤10MB) via `POST /projects/{project_id}/tasks/{id}/attachments` THEN o sistema SHALL armazená-lo através da abstração de storage configurada e retornar a URL/referência do anexo.
2. WHEN um usuário envia um arquivo maior que 10MB THEN o sistema SHALL retornar 413 sem salvar.
3. WHEN o storage configurado falha ao salvar o anexo THEN o sistema SHALL retornar 5xx sem afetar os demais dados já salvos da tarefa.
4. WHEN um usuário remove um anexo via `DELETE /projects/{project_id}/tasks/{id}/attachments/{attachment_id}` THEN o sistema SHALL apagá-lo do storage e da lista de anexos da tarefa.

**Independent Test**: subir um anexo → confirmar referência na tarefa → remover → confirmar que some da listagem.

---

## Edge Cases

- WHEN o e-mail de registro não é um e-mail válido THEN o sistema SHALL retornar 422.
- WHEN a senha tem menos de 8 caracteres THEN o sistema SHALL retornar 422.
- WHEN um projeto ou tarefa referenciado por ID não existe (ou não pertence ao usuário) THEN o sistema SHALL retornar 404.
- WHEN uma tarefa é criada sem prazo THEN o sistema SHALL aceitar prazo nulo sem erro.
- WHEN uma tarefa é criada sem tags THEN o sistema SHALL aceitar lista vazia sem erro.
- WHEN o refresh token expira ou é inválido THEN `POST /auth/refresh` SHALL retornar 401, forçando novo login.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| AUTH-01 | P1: Autenticação — registro | Design | Pending |
| AUTH-02 | P1: Autenticação — login + cookies | Design | Pending |
| AUTH-03 | P1: Autenticação — refresh | Design | Pending |
| AUTH-04 | P1: Autenticação — logout | Design | Pending |
| AUTH-05 | P1: Autenticação — rate limit login | Design | Pending |
| ISO-01 | P1: Isolamento — 401 sem sessão | Design | Pending |
| ISO-02 | P1: Isolamento — 404 cross-user | Design | Pending |
| PROJ-01 | P1: Projetos — criar | Design | Pending |
| PROJ-02 | P1: Projetos — listar | Design | Pending |
| PROJ-03 | P1: Projetos — renomear | Design | Pending |
| PROJ-04 | P1: Projetos — deletar (bloqueio) | Design | Pending |
| TASK-01 | P1: Tarefas — criar | Design | Pending |
| TASK-02 | P1: Tarefas — editar campos | Design | Pending |
| TASK-03 | P1: Tarefas — listar por projeto | Design | Pending |
| TASK-04 | P1: Tarefas — deletar | Design | Pending |
| STAT-01 | P1: Status — transições livres | Design | Pending |
| TAG-01 | P2: Tags — salvar | Design | Pending |
| TAG-02 | P2: Tags — limite 20 chars | Design | Pending |
| ATT-01 | P2: Anexos — upload | Design | Pending |
| ATT-02 | P2: Anexos — limite de tamanho | Design | Pending |
| ATT-03 | P2: Anexos — remoção | Design | Pending |

**ID format:** `[CATEGORY]-[NUMBER]`

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 20 total, 0 mapped to tasks, 20 unmapped ⚠️ (Design phase ainda não iniciada)

---

## Success Criteria

- [ ] Fluxo completo registro → login → criar projeto → criar tarefa → editar todos os campos → mudar status → deletar funciona via API sem erros
- [ ] Isolamento de dados 100% garantido entre usuários (testável com 2+ usuários)
- [ ] Todos os endpoints documentados via OpenAPI (gerado automaticamente pelo FastAPI)
- [ ] Upload/remoção de anexos funciona tanto com storage local (dev) quanto S3 (prod), sem alterar código de negócio
- [ ] `/docs` (Swagger UI) e `/openapi.json` refletem 100% dos endpoints implementados, sem documentação manual paralela a manter
- [ ] Container roda como usuário não-root, sem permissão de escrita fora dos diretórios explicitamente necessários (ex.: pasta de anexos locais)
