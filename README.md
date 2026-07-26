# Taskly API

Backend do **Taskly**, um sistema de gestão de tarefas pessoais — case técnico da vaga de Desenvolvedor Fullstack (UEX Startup Studio). API REST em FastAPI, autenticação própria via JWT em cookies httpOnly, projetos e tarefas com anexos, storage desacoplado (local em dev, S3 em produção).

O frontend (React) vive em repositório separado: [`../frontend`](../frontend).

## Stack

- **Python 3.12+** gerenciado por [`uv`](https://docs.astral.sh/uv/) (sem pip/venv/poetry manual)
- **FastAPI** + **Pydantic** — API REST, validação, OpenAPI automático
- **SQLAlchemy 2.0 (async)** + `asyncpg` — acesso a dados
- **Alembic** — migrations versionadas
- **PostgreSQL 16**
- **PyJWT** + `passlib[bcrypt]` — autenticação
- **pytest** + `pytest-asyncio` + `httpx` — testes unitários e de integração (contra Postgres real)
- **pip-audit** — auditoria de vulnerabilidades de dependências

Arquitetura em camadas: `routers → services → repositories → SQLAlchemy → Postgres`. Detalhes completos (diagramas, modelos de dados, decisões técnicas e trade-offs) em [`.specs/features/taskly-api/design.md`](.specs/features/taskly-api/design.md).

## Setup local

Pré-requisitos: [`uv`](https://docs.astral.sh/uv/getting-started/installation/) instalado, Docker (para o Postgres de desenvolvimento).

```bash
# 1. Instalar dependências (cria o .venv automaticamente)
uv sync --locked

# 2. Copiar e preencher as variáveis de ambiente
cp .env.example .env

# 3. Subir o Postgres de desenvolvimento
docker compose up -d

# 4. Aplicar as migrations
uv run alembic upgrade head

# 5. Subir a API em modo dev (reload automático)
uv run uvicorn app.main:app --reload
```

A API sobe em `http://localhost:8000`. Documentação interativa (Swagger) em `http://localhost:8000/docs`, OpenAPI JSON em `/openapi.json`, Redoc em `/redoc` — gerados automaticamente pelo FastAPI a partir das rotas e schemas Pydantic, sempre em sincronia com o código.

## Variáveis de ambiente

Todas documentadas em [`.env.example`](.env.example) (sem valores reais). Nunca commitar `.env`.

| Variável | Obrigatória | Descrição |
| --- | --- | --- |
| `DATABASE_URL` | sim | String de conexão async do Postgres (`postgresql+asyncpg://...`) |
| `JWT_SECRET` | sim | Segredo para assinar os access tokens JWT — usar um valor longo e aleatório em produção |
| `JWT_ACCESS_TTL_MINUTES` | não (default 15) | Duração do access token |
| `JWT_REFRESH_TTL_DAYS` | não (default 7) | Duração do refresh token |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | não (default 5) | Tentativas de login falhas antes do bloqueio (429) |
| `LOGIN_RATE_LIMIT_WINDOW_MINUTES` | não (default 15) | Janela de tempo do rate limit |
| `STORAGE_BACKEND` | não (default `local`) | `local` ou `s3` — abstração de storage de anexos |
| `LOCAL_STORAGE_PATH` | se `STORAGE_BACKEND=local` | Diretório local para anexos |
| `S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | se `STORAGE_BACKEND=s3` | Credenciais/bucket do S3 |
| `CORS_ORIGIN` | não (default `http://localhost:5173`) | Origem única liberada para requisições com cookies (frontend) |
| `COOKIE_SECURE` | não (default `false`) | `true` em produção (HTTPS) — ativa o atributo `Secure` dos cookies de sessão |

## Testes

```bash
# Suíte completa (unit + integration — precisa do Postgres do docker compose rodando)
uv run pytest -q

# Só testes unitários (rápido, sem banco)
uv run pytest tests/unit -q

# Auditoria de dependências
uv run pip-audit
```

Estratégia de testes, matriz de cobertura por camada e comandos de gate: [`.specs/features/taskly-api/tasks.md`](.specs/features/taskly-api/tasks.md#test-coverage-matrix).

## Docker (produção)

Imagem multi-stage: o stage `builder` resolve as dependências com `uv`, o stage `runtime` final não contém `uv` nem toolchain de build — só o virtualenv e o código da aplicação, rodando como usuário não-root (`appuser`).

```bash
docker compose up -d --build
```

Isso sobe Postgres e API juntos na mesma rede do compose; o serviço `api` usa `DATABASE_URL=postgresql+asyncpg://taskly:taskly@postgres:5432/taskly` (hostname do serviço, não `localhost` — dentro do container `localhost` aponta para si mesmo, não para o host). O restante das variáveis vem do `.env` local via `env_file`.

Migrations rodam automaticamente no start do container (`alembic upgrade head`) antes de subir o servidor — ver `entrypoint.sh`.

## Deploy (AWS — EC2, sem domínio próprio)

**EC2** roda tudo: o backend (container Docker, porta 8000 vinculada só a `127.0.0.1`), o Postgres (container, `docker-compose.yml`) e um **Nginx** na frente servindo o build estático do frontend (repositório separado, mesma instância) e fazendo proxy de `/api/*` pro container do backend. Anexos vão pro **S3** (`STORAGE_BACKEND=s3`). Nenhuma mudança de código entre dev e produção — só variáveis de ambiente. Passo a passo completo de provisionamento (S3, IAM, EC2, Nginx):

- `DATABASE_URL` → `postgresql+asyncpg://taskly:<senha>@postgres:5432/taskly` (Postgres roda em container na mesma EC2 — sem Aurora neste deploy)
- `STORAGE_BACKEND=s3` + credenciais/bucket (anexos)
- `CORS_ORIGIN` — sem efeito prático neste modelo (frontend e backend são a mesma origem via Nginx), mas mantido preenchido por segurança
- `COOKIE_SECURE=false` — **decisão deliberada, não descuido**: sem domínio próprio não tem HTTPS de verdade (Let's Encrypt/ACM exigem domínio), então a app fica em `http://<IP-da-EC2>` puro. `Secure=true` faria o navegador descartar o cookie de sessão nessa conexão.
- `JWT_SECRET` com um valor real e secreto (`openssl rand -hex 32`, nunca reaproveitar o do `.env.example`)

### CI/CD (GitHub Actions)

Workflow em [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml): a cada push em `master`, roda a suíte completa + `pip-audit` e, se passar, conecta na EC2 via SSH e faz `git reset --hard` + `docker compose up -d --build`. Segredos necessários no repositório (**Settings → Secrets and variables → Actions**):

| Secret | Valor |
| --- | --- |
| `EC2_HOST` | IP público ou DNS da instância |
| `EC2_USER` | usuário SSH (ex. `ubuntu`) |
| `EC2_SSH_KEY` | conteúdo da chave privada (`.pem`) usada pra conectar |

O `.env` com os segredos da aplicação (JWT, banco, S3) fica só na instância EC2 — nunca passa pelo GitHub Actions. O repositório `frontend` usa os **mesmos** três secrets (mesma EC2) pro próprio deploy.

## Segurança — decisões relevantes

- Senhas com `bcrypt`; sessão via JWT de curta duração (access token) + refresh token opaco persistido (hash) no banco, com rotação a cada refresh e revogação real no logout.
- Cookies de sessão `httpOnly` + `SameSite=Lax` (+ `Secure` em produção) — o frontend nunca lê o token via JS.
- Toda rota de projeto/tarefa exige sessão válida (401 sem cookie) e verifica que o recurso pertence ao usuário autenticado antes de qualquer leitura/mutação (404 para acesso cross-user, nunca 403 — não revela a existência do recurso).
- Rate limit de login (5 tentativas / 15 min).
- Dependências com versão fixada + lockfile versionado + `pip-audit` no setup/CI — mitigação contra supply-chain attacks.
- Anexos limitados a 10MB; falha de storage nunca corrompe os demais dados já salvos da tarefa.

## Documentação do processo (spec-driven + uso de IA)

Este backend foi construído com desenvolvimento orientado a especificação (Specify → Design → Tasks → Execute, com verificação independente ao final), assistido por IA (Claude Code). Todo o histórico de decisões técnicas, trade-offs e o relatório de verificação ficam versionados em [`.specs/`](.specs/):

- [`spec.md`](.specs/features/taskly-api/spec.md) — requisitos e critérios de aceite rastreáveis
- [`design.md`](.specs/features/taskly-api/design.md) — arquitetura, modelos de dados, decisões técnicas
- [`tasks.md`](.specs/features/taskly-api/tasks.md) — quebra em tarefas atômicas com critério de verificação
- [`validation.md`](.specs/features/taskly-api/validation.md) — relatório do Verifier independente (cobertura por critério de aceite + testes de mutação)
- [`STATE.md`](.specs/STATE.md) — log de decisões de projeto (`AD-NNN`, com data e justificativa) e histórico de handoff
- [`LESSONS.md`](.specs/LESSONS.md) — lições extraídas das falhas encontradas na verificação
