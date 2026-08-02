# Groups & RBAC Specification

## Problem Statement

Hoje o Taskly é estritamente single-user: todo projeto pertence a exatamente
um usuário (`Project.user_id`), sem nenhuma forma de colaboração. Esta
feature expande a ideia já registrada em
`.specs/features/taskly-api/spec.md` ("Ideia para versão futura (v2) —
Grupos/times com RBAC") para uma spec de verdade: usuários podem criar
grupos, convidar outras pessoas via link, e compartilhar projetos com o
grupo — com dois papéis (Owner/Membro) controlando quem pode gerenciar o
grupo versus quem só colabora dentro dele.

**Cardinalidade grupo↔projeto (explícito pra não sobrar ambiguidade)**: um
**grupo pode ter vários projetos vinculados** (ex.: um Owner acompanhando
todos os projetos do time num só lugar) — a restrição é a inversa: **cada
projeto individual pertence a no máximo um grupo por vez**. É uma relação
N:1 (muitos projetos → um grupo), nunca 1:1.

## Goals

- [ ] Usuário consegue criar um grupo, convidar outra pessoa e colaborar com
      ela num projeto compartilhado, de ponta a ponta, sem enviar e-mail
      nenhum de verdade.
- [ ] Isolamento de dados do v1 (usuário só acessa o que é seu) nunca
      regride — grupos são **aditivos**: ampliam acesso, nunca retiram
      acesso que já existia.
- [ ] RBAC de dois papéis (Owner/Membro) aplicado de forma consistente com o
      padrão de ownership check já estabelecido no v1 (AD-012).

## Out of Scope

Explicitamente excluído desta v2. Documentado pra não expandir escopo.

| Feature | Reason |
| --- | --- |
| Envio de e-mail real (SES/Postmark/SendGrid) | Decisão do usuário: convite por link/token evita depender de infra de e-mail nova neste momento. Vira v3 se for necessário. |
| Papel "Viewer" (só leitura) | Usuário optou por só Owner/Membro pro MVP desta feature — um terceiro papel fica pra depois se fizer falta na prática. |
| Projeto vinculado a múltiplos grupos simultaneamente | Usuário confirmou: no máximo 1 grupo por projeto — mantém o modelo de autorização simples (quem pode acessar X é sempre determinístico). |
| Migração automática de projetos existentes para dentro de um grupo | Usuário confirmou: projetos continuam pessoais até serem vinculados explicitamente — zero risco de expor dado antigo sem querer. |
| Múltiplos owners por grupo | Usuário confirmou: exatamente 1 owner, transferível — evita ambiguidade de "quem manda". |
| Notificação (e-mail/in-app/push) de convite, remoção, etc. | Sem infra de notificação no projeto hoje; fora do escopo desta feature. |
| Log de atividade / audit trail do grupo | Observabilidade estruturada é um gap já conhecido do projeto inteiro (v1), não algo a resolver só para grupos. |
| Sub-grupos / hierarquia de grupos | Não pedido, adiciona complexidade de modelo sem necessidade demonstrada. |
| Busca de usuário por e-mail pra convidar diretamente | Sem fluxo de e-mail real, convite é só por link — busca de usuário abriria uma superfície de enumeração de contas fora de escopo. |

---

## Assumptions & Open Questions

Toda ambiguidade discutida com o usuário está resolvida abaixo. As demais
(não levantadas em Discuss) são assumidas com racional explícito.

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Forma de convite | Link com token único, sem e-mail real | Confirmado pelo usuário | y |
| Papéis | Owner + Membro (2 papéis) | Confirmado pelo usuário | y |
| Grupo↔projeto | Um grupo pode ter **vários** projetos vinculados; cada projeto pertence a no máximo **1** grupo por vez (N:1) | Confirmado pelo usuário — corrigido explicitamente após ambiguidade na pergunta original (usuário quer acompanhar vários projetos do time como Owner de um único grupo) | y |
| Projetos existentes | Continuam pessoais até vínculo explícito | Confirmado pelo usuário | y |
| Expiração do convite | 7 dias | Confirmado pelo usuário | y |
| Ownership do grupo | Exatamente 1 owner, transferível | Confirmado pelo usuário | y |
| Delete de grupo com projeto vinculado | Bloqueado (409) até desvincular | Confirmado pelo usuário | y |
| Tarefas de membro removido | Permanecem no projeto do grupo | Confirmado pelo usuário | y |
| **Modelo de dados do vínculo** | `Project` ganha `group_id` **nullable**, mantendo `user_id` (dono/criador original) inalterado. Acesso = `user_id == current_user` **OU** (`group_id` setado **E** `current_user` é membro daquele grupo). | Extensão aditiva pura sobre o modelo do v1 — não quebra `ProjectRepository.get_for_user`/AD-012, só amplia a checagem. Desvincular (`group_id = null`) automaticamente devolve o acesso a "só o dono original", sem precisar decidir "quem vira o novo dono". | n (default do agente) |
| **Quem pode vincular/desvincular projeto ↔ grupo** | Só o **Owner do grupo**, e só projetos dos quais o próprio Owner é o `user_id` (dono) | Mantém consistência com o resto do RBAC: Owner administra a composição do grupo (convite, remoção, exclusão), Membro só opera dentro do que já está vinculado. Evita um Membro "puxar" um projeto próprio pro grupo sem alinhamento do Owner. | n (default do agente) |
| **Convite é single-use ou reutilizável** | Single-use — cada link de convite gerado é consumido por exatamly uma pessoa; Owner gera um novo link por pessoa que quiser convidar | Mais simples e seguro (evita fan-out indefinido de um link vazado); não foi pedido suporte a "link público reutilizável" tipo Discord. | n (default do agente) |
| **Owner tentando sair do grupo sem transferir posse antes** | Bloqueado (409) — precisa transferir a posse pra outro membro primeiro | Consequência direta de "exatamente 1 owner sempre" já confirmado — nunca pode existir grupo sem owner. | n (default do agente) |
| **Rate limit de geração de convite** | 10 convites gerados por Owner por grupo, por janela de 1 hora | Dimensão "auth boundaries" exige alguma proteção contra abuso; número não especificado pelo usuário, análogo ao padrão já usado em `LOGIN_RATE_LIMIT_*` no v1. | n (default do agente) |
| **Tamanho do nome do grupo** | 1–100 caracteres | Mesmo limite já usado em `ProjectCreateRequest.name` (`app/api/routers/projects.py:18`) — consistência de convenção. | n (default do agente) |
| **Observabilidade (logging de ações de grupo)** | N/A — não endereçado nesta feature | Gap já conhecido do projeto inteiro (v1 nunca implementou logging estruturado); resolver só para grupos seria inconsistente. Fica para uma iniciativa de observabilidade do projeto como um todo. | n/a |
| **Falha de dependência externa (e-mail)** | N/A — não se aplica | Convite por link/token foi escolhido justamente para não introduzir uma dependência externa nesta feature. | n/a |

**Open questions:** none — all resolved or logged above.

---

## User Stories

### P1: Criar grupo, convidar e colaborar ⭐ MVP

**User Story**: Como usuário, quero criar um grupo, convidar outra pessoa via
link e compartilhar um projeto com ela, para que a gente colabore nas mesmas
tarefas sem precisar dividir credenciais.

**Why P1**: É o caminho feliz completo — sem isso, não existe feature de
colaboração nenhuma pra demonstrar.

**Acceptance Criteria**:

1. WHEN um usuário autenticado envia `POST /groups` com um nome válido (1–100 caracteres) THEN o sistema SHALL criar o grupo e tornar esse usuário automaticamente seu Owner, retornando 201.
2. WHEN o Owner de um grupo envia `POST /groups/{group_id}/invites` THEN o sistema SHALL gerar um token de convite único, hasheado em repouso (mesmo padrão do refresh token do v1), com expiração em 7 dias, e retornar o link/token em texto plano **apenas nesta resposta** (nunca recuperável depois).
3. WHEN um usuário que não é o Owner do grupo tenta gerar um convite (`POST /groups/{group_id}/invites`) THEN o sistema SHALL retornar 403 sem criar nenhum convite.
4. WHEN um usuário autenticado (diferente de quem já está no grupo) acessa `POST /invites/{token}/accept` com um token válido e não expirado THEN o sistema SHALL criar sua membership como Membro, marcar o token como consumido (single-use) e retornar 200 com os dados do grupo.
5. WHEN o mesmo token de convite é usado uma segunda vez (já consumido) THEN o sistema SHALL retornar 409 sem criar membership duplicada.
6. WHEN um token de convite expirado (>7 dias) é usado THEN o sistema SHALL retornar 410 sem criar membership.
7. WHEN o Owner de um grupo envia `POST /groups/{group_id}/projects/{project_id}/link`, sendo ele o dono (`user_id`) desse projeto THEN o sistema SHALL setar `Project.group_id` para o grupo e retornar 200.
8. WHEN um usuário tenta vincular ao grupo um projeto do qual não é o dono (`user_id` diferente) THEN o sistema SHALL retornar 403/404 (mesmo padrão de ocultação de existência do v1, AD-012).
9. WHEN um usuário tenta vincular um projeto que já está vinculado a outro grupo THEN o sistema SHALL retornar 409 (precisa desvincular do grupo atual primeiro).
10. WHEN um Membro (não-Owner) de um grupo acessa as tarefas de um projeto vinculado a esse grupo (`GET/POST/PATCH/DELETE .../tasks/...`) THEN o sistema SHALL permitir a operação com os mesmos direitos do dono original (CRUD completo de tarefas).
11. WHEN um usuário que **não** é membro do grupo dono de um projeto tenta acessar as tarefas desse projeto THEN o sistema SHALL retornar 403/404, idêntico ao comportamento de isolamento do v1 (nenhuma regressão).
12. WHEN o Owner acessa `GET /groups/{group_id}/members` THEN o sistema SHALL retornar a lista de membros com seus papéis (Owner/Membro) e data de entrada.

**Independent Test**: Criar grupo com o usuário A, gerar convite, aceitar com
o usuário B, vincular um projeto de A ao grupo, e confirmar que B consegue
criar/editar uma tarefa nesse projeto — enquanto um terceiro usuário C
(fora do grupo) continua recebendo 403/404 ao tentar acessar o mesmo
projeto.

---

### P2: Gestão de ciclo de vida do grupo

**User Story**: Como Owner de um grupo, quero remover membros, transferir a
posse, revogar convites, desvincular projetos e excluir o grupo, para
manter o grupo organizado conforme a colaboração muda.

**Why P2**: Refinamentos necessários pra um grupo ser administrável de
verdade ao longo do tempo, mas não bloqueiam a demonstração do caminho
feliz de colaboração (P1).

**Acceptance Criteria**:

1. WHEN o Owner envia `DELETE /groups/{group_id}/members/{user_id}` THEN o sistema SHALL remover a membership, revogando o acesso desse usuário aos projetos do grupo imediatamente — as tarefas que ele criou permanecem no projeto.
2. WHEN um Membro envia `POST /groups/{group_id}/leave` THEN o sistema SHALL remover sua própria membership e retornar 200.
3. WHEN o Owner envia `POST /groups/{group_id}/leave` (ou tenta se auto-remover) sem antes transferir a posse THEN o sistema SHALL retornar 409 (nunca pode existir grupo sem owner).
4. WHEN o Owner envia `POST /groups/{group_id}/transfer-ownership` apontando outro membro existente THEN o sistema SHALL promover esse membro a Owner e rebaixar o Owner anterior a Membro, atomicamente.
5. WHEN o Owner envia `DELETE /groups/{group_id}/invites/{invite_id}` para um convite ainda pendente THEN o sistema SHALL invalidar o token imediatamente (uso subsequente retorna 410).
6. WHEN o Owner envia `POST /groups/{group_id}/projects/{project_id}/unlink` THEN o sistema SHALL zerar `Project.group_id`, revertendo o acesso pro dono original apenas (`user_id`).
7. WHEN o Owner tenta `DELETE /groups/{group_id}` enquanto ainda existe ao menos um projeto com `group_id` apontando pra esse grupo THEN o sistema SHALL retornar 409 sem excluir nada.
8. WHEN o Owner tenta `DELETE /groups/{group_id}` sem nenhum projeto vinculado THEN o sistema SHALL excluir o grupo e suas memberships/convites pendentes em cascata, retornando 204.
9. WHEN o Owner envia `PATCH /groups/{group_id}` com um novo nome válido THEN o sistema SHALL renomear o grupo e retornar 200.
10. WHEN qualquer ação de gestão (remover membro, transferir posse, revogar convite, desvincular projeto, excluir grupo, renomear) é tentada por um Membro (não-Owner) THEN o sistema SHALL retornar 403.

**Independent Test**: Com o grupo/projeto do teste de P1 já criado, remover
o usuário B, confirmar que ele perde acesso imediatamente (403/404 nas
tarefas do projeto), depois desvincular o projeto e confirmar que só A
continua tendo acesso, e por fim excluir o grupo.

---

### P3: Visibilidade adicional

**User Story**: Como usuário, quero ver todos os grupos dos quais participo
e os convites pendentes de um grupo que eu administro, para ter uma visão
completa sem precisar adivinhar.

**Why P3**: Melhora de usabilidade sobre o que já funciona em P1/P2 — não é
bloqueante pro caminho feliz de colaboração.

**Acceptance Criteria**:

1. WHEN um usuário autenticado acessa `GET /groups` THEN o sistema SHALL retornar todos os grupos dos quais ele é Owner ou Membro, com seu papel em cada um.
2. WHEN o Owner acessa `GET /groups/{group_id}/invites` THEN o sistema SHALL retornar os convites ainda pendentes (não aceitos, não expirados, não revogados) daquele grupo.

---

## Edge Cases

- WHEN um convite é gerado mas o grupo é excluído antes de ser aceito (só possível se nenhum projeto estiver vinculado) THEN o sistema SHALL invalidar o convite (accept retorna 404).
- WHEN o Owner gera mais de 10 convites em menos de 1 hora THEN o sistema SHALL bloquear novas gerações temporariamente (429), mesmo padrão de rate limit do login do v1.
- WHEN um usuário já é Membro do grupo e tenta aceitar um novo convite pro mesmo grupo THEN o sistema SHALL retornar 409 (já é membro).
- WHEN um projeto vinculado a um grupo é excluído (fluxo já existente do v1, `DELETE /projects/{id}`) THEN o sistema SHALL seguir a regra já existente do v1 (bloqueado se tiver tarefas) — a existência de `group_id` não muda essa regra.
- WHEN o nome do grupo tem menos de 1 ou mais de 100 caracteres THEN o sistema SHALL retornar 422 (mesmo padrão de validação de `ProjectCreateRequest`).
- WHEN um usuário tenta transferir a posse do grupo para alguém que não é membro dele THEN o sistema SHALL retornar 404/422 sem realizar a transferência.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| GRP-01 | P1: Criar grupo | Design | Pending |
| GRP-02 | P1: Gerar convite | Design | Pending |
| GRP-03 | P1: Aceitar convite | Design | Pending |
| GRP-04 | P1: Vincular projeto | Design | Pending |
| GRP-05 | P1: RBAC em tarefas do projeto vinculado | Design | Pending |
| GRP-06 | P1: Listar membros | Design | Pending |
| GRP-07 | P2: Remover membro | Design | Pending |
| GRP-08 | P2: Sair do grupo | Design | Pending |
| GRP-09 | P2: Transferir posse | Design | Pending |
| GRP-10 | P2: Revogar convite | Design | Pending |
| GRP-11 | P2: Desvincular projeto | Design | Pending |
| GRP-12 | P2: Excluir grupo | Design | Pending |
| GRP-13 | P2: Renomear grupo | Design | Pending |
| GRP-14 | P3: Listar meus grupos | Design | Pending |
| GRP-15 | P3: Listar convites pendentes | Design | Pending |

**ID format:** `GRP-NN`

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 15 total, 0 mapped to tasks, 15 unmapped ⚠️ (esperado — Design/Tasks ainda não rodaram)

---

## Success Criteria

- [ ] Usuário A cria grupo, convida B por link, B aceita, A vincula um
      projeto próprio ao grupo, e B consegue criar/editar tarefa nesse
      projeto — tudo sem nenhum envio de e-mail real.
- [ ] Usuário C (fora do grupo) nunca consegue acessar o projeto vinculado
      ao grupo — zero regressão no isolamento de dados do v1.
- [ ] Toda ação de gestão do grupo (convidar, remover, transferir, excluir,
      (des)vincular) só é permitida para o Owner — Membro recebe 403 em
      todas elas.
- [ ] Suíte de testes do backend cresce sem quebrar nenhum teste existente
      do v1 (baseline: 201 passando).
