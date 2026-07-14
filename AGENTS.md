# AGENTS

## Okidoo Fork Operational Notes

These notes capture the Okidoo-specific work and production topology for this
fork. Keep them current when changing routing, migrations, deployment paths, or
the production service layout.

### Repository And Remotes

- Local project path: `/Users/michaellavigne/Documents/projets/codex-lb`
- Fork remote: `origin = https://github.com/Okidoo/codex-lb.git`
- Upstream remote: `upstream = https://github.com/Soju06/codex-lb.git`
- Main fork/upstream merge branch: `codex/upstream-model-sources-zai`
- Current deployed fork commit as of 2026-07-14: `a6c46d3b`
- Current production image as of 2026-07-14:
  `docker.okidoo.co/okidoo/codex-lb:a6c46d3b`

Do not assume Docker exists on the local Mac workspace. During the July 2026
deployment, Docker was not installed locally. Use `ssh mike@work` for Docker
build/push unless a harmless check shows local Docker is available.

### Fork Features To Preserve

- Z.AI provider support:
  - `accounts.provider` supports `openai` and `zai`.
  - Z.AI credentials are stored encrypted in `zai_credentials`.
  - Z.AI accounts are created with `POST /api/accounts/zai`.
  - Z.AI quota/usage support exists for 5h and weekly windows where supported.
- GLM routing:
  - GLM requests route to Z.AI accounts through the local Z.AI adapter.
  - GPT/Codex/OpenAI requests route through normal OpenAI accounts.
  - `gpt-5.2` is intentionally reserved as a compatibility slug for Codex
    Desktop / VS Code. It is displayed as `GLM-5.2` and routes to `glm-5.2`.
  - Do not restore the old dashboard/database model alias system unless the
    user explicitly asks. The `gpt-5.2 -> glm-5.2` mapping is static fork
    policy.
- Upstream `model_sources`:
  - Keep upstream's `model_sources` support for generic OpenAI-compatible
    external sources.
  - Do not model Z.AI Coding Plan as a generic model source. Z.AI uses the
    integrated provider, account pool, quota handling, and adapter.
- Codex setup/catalog:
  - `/codex/setup/*` and `/codex/catalog.json` are fork behavior.
  - The setup intentionally uses normal Codex auth/API-key flow, not a required
    extra environment variable.
  - The catalog must keep `gpt-5.2` displayed as `GLM-5.2` for app dropdown
    compatibility, plus real `glm-5.2` for clients that accept the slug.
- Chrome Debug Bridge:
  - Backend module: `app/modules/chrome_debug`
  - Frontend feature: `frontend/src/features/chrome-debug`
  - Migration: `20260710_000000_add_chrome_debug_bridge`
  - Provides a raw CDP relay between API-key-authorized Codex clients and Chrome
    browsers registered by the companion extension.
  - Chrome Debug access must be explicitly granted to API keys. Do not make it
    default-open.

### Alembic Migration Gotcha

The first Chrome Debug deployment failed because Alembic had two heads:

- `20260710_000000_add_chrome_debug_bridge`
- `20260711_030000_add_limit_warmup_idle_threshold`

The fix was to make the Chrome Debug migration depend on both the Z.AI fork
branch and the upstream warmup branch:

```python
down_revision = (
    "20260707_020000_add_zai_credential_key_id",
    "20260711_030000_add_limit_warmup_idle_threshold",
)
```

Before deploying schema changes, verify that the migration graph has exactly
one Alembic head:

```sh
uv run python - <<'PY'
from app.db.migrate import _build_alembic_config
from alembic.script import ScriptDirectory

cfg = _build_alembic_config("sqlite:////tmp/codex-lb-head-check.db")
script = ScriptDirectory.from_config(cfg)
print(script.get_heads())
print(script.get_current_head())
PY
```

Also test `upgrade head` against a copy of the production SQLite database before
switching the production container.

### Production Topology

Public service:

```text
https://codex.okidoo.co
```

Nginx Proxy Manager:

- Master host: `ssh okidoo@10.0.9.144`
- Container: `nginx_balancers_nginx-balancers_1`
- SQLite DB: `/home/okidoo/nginx_balancers/data/database.sqlite`
- Proxy host for `codex.okidoo.co`:
  - NPM proxy host id: `154`
  - Forward target: `http://172.31.254.140:2455`

Real backend VM:

- Proxmox host: `ssh root@192.168.80.21`
- VM id: `124`
- VM name: `codex-lb-124`
- LAN IP: `192.168.80.81`
- WireGuard IP used by NPM: `172.31.254.140`
- WireGuard interface: `wg-codexlb`

Production stack inside VM 124:

- Compose file: `/opt/codex-lb/docker-compose.yml`
- Data directory: `/opt/codex-lb/data`
- Env file: `/opt/codex-lb/.env.local`
- Service to replace during deploy: `codex-lb`
- Current image line should look like:
  `image: docker.okidoo.co/okidoo/codex-lb:<commit>`

The stack also includes `headroom-gate`, `headroom`, and `headroom-redirect`.
`headroom-gate` is Caddy listening on host port `2455`. It routes most LLM
endpoints through `headroom`, which forwards to `codex-lb:2455`. Compact
endpoints and dashboard/API routes go directly to `codex-lb`.

### Safe Production Checks

Public health:

```sh
curl -sS --max-time 10 -D - https://codex.okidoo.co/health/ready
```

Container state through Proxmox guest agent:

```sh
ssh root@192.168.80.21 \
  'qm guest exec 124 -- docker ps --filter name=codex-lb --format "{{.Names}} {{.Image}} {{.Status}}"'
```

Compose image line:

```sh
ssh root@192.168.80.21 \
  'qm guest exec 124 -- grep -n "image: docker.okidoo.co/okidoo/codex-lb" /opt/codex-lb/docker-compose.yml'
```

Internal VM health:

```sh
ssh root@192.168.80.21 \
  'qm guest exec 124 -- curl -sS --max-time 5 http://127.0.0.1:2455/health/ready'
```

The QEMU guest agent on VM 124 can be fragile with long or noisy commands and
has returned signal 11 before. Prefer small commands, quiet Docker output
(`docker pull -q`), and separate steps. Direct SSH to `192.168.80.81` may fail
because of local host-key/auth state; the reliable route from this workspace is
usually `ssh root@192.168.80.21 'qm guest exec 124 -- ...'`.

### Deployment Workflow

This service may be the gateway used by the current Codex session. Keep the
running production container unchanged until the image is pushed, pulled,
smoke-tested, and rollback material exists.

Build and push from `mike@work`:

```sh
ssh mike@work '
set -euo pipefail
BUILD_DIR=/tmp/codex-lb-deploy-<commit>
rm -rf "$BUILD_DIR"
git clone --branch codex/upstream-model-sources-zai --single-branch \
  git@github.com:Okidoo/codex-lb.git "$BUILD_DIR"
cd "$BUILD_DIR"
git rev-parse --short HEAD
docker build --pull -t docker.okidoo.co/okidoo/codex-lb:<commit> .
docker push docker.okidoo.co/okidoo/codex-lb:<commit>
'
```

Pull on VM 124, but do not switch yet:

```sh
ssh root@192.168.80.21 \
  'qm guest exec 124 -- docker pull -q docker.okidoo.co/okidoo/codex-lb:<commit>'
```

Back up compose:

```sh
ssh root@192.168.80.21 \
  'qm guest exec 124 -- cp /opt/codex-lb/docker-compose.yml /opt/codex-lb/docker-compose.yml.backup-before-<commit>-<timestamp>'
```

Back up the production SQLite DB:

```sh
ssh root@192.168.80.21 \
  'qm guest exec 124 -- python3 -c "import sqlite3, os; dst=\"/opt/codex-lb/data/store.db.backup-before-<commit>-<timestamp>\"; os.path.exists(dst) and os.remove(dst); src=sqlite3.connect(\"/opt/codex-lb/data/store.db\"); out=sqlite3.connect(dst); src.backup(out); out.close(); src.close()"'
```

Test migrations on a DB copy:

```sh
ssh root@192.168.80.21 \
  'qm guest exec 124 -- python3 -c "import sqlite3, os; dst=\"/opt/codex-lb/data/store.db.migration-test-<commit>\"; os.path.exists(dst) and os.remove(dst); src=sqlite3.connect(\"/opt/codex-lb/data/store.db\"); out=sqlite3.connect(dst); src.backup(out); out.close(); src.close()"'

ssh root@192.168.80.21 \
  'qm guest exec 124 -- chown --reference=/opt/codex-lb/data/store.db /opt/codex-lb/data/store.db.migration-test-<commit>'

ssh root@192.168.80.21 \
  'qm guest exec 124 -- docker run --rm --entrypoint python -v /opt/codex-lb/data:/data docker.okidoo.co/okidoo/codex-lb:<commit> -m app.db.migrate --db-url sqlite+aiosqlite:////data/store.db.migration-test-<commit> upgrade head'
```

Optional but recommended: smoke-start the new image against the migrated DB copy
with the real env file:

```sh
ssh root@192.168.80.21 \
  'qm guest exec 124 -- docker run -d --name codex-lb-smoke-<commit> --env-file /opt/codex-lb/.env.local -e CODEX_LB_DATABASE_URL=sqlite+aiosqlite:////data/store.db.migration-test-<commit> -v /opt/codex-lb/data:/data docker.okidoo.co/okidoo/codex-lb:<commit>'

ssh root@192.168.80.21 \
  "qm guest exec 124 -- docker exec codex-lb-smoke-<commit> python -c 'import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:2455/health/ready\", timeout=5).read().decode())'"

ssh root@192.168.80.21 \
  'qm guest exec 124 -- docker rm -f codex-lb-smoke-<commit>'
```

Switch only at the last minute:

```sh
ssh root@192.168.80.21 \
  'qm guest exec 124 -- sed -i s#docker.okidoo.co/okidoo/codex-lb:<old>#docker.okidoo.co/okidoo/codex-lb:<commit># /opt/codex-lb/docker-compose.yml'

ssh root@192.168.80.21 \
  'qm guest exec 124 -- docker compose -f /opt/codex-lb/docker-compose.yml config --services'

ssh root@192.168.80.21 \
  'qm guest exec 124 -- docker compose -f /opt/codex-lb/docker-compose.yml up -d --no-deps codex-lb'
```

Verify immediately with the public health URL, container state, and recent
`docker logs --tail 120 codex-lb`.

### Rollback

Fast rollback target before the July 2026 Chrome Debug deployment:

```text
docker.okidoo.co/okidoo/codex-lb:74a911a5
```

Fast rollback commands:

```sh
ssh root@192.168.80.21 \
  'qm guest exec 124 -- sed -i s#docker.okidoo.co/okidoo/codex-lb:<bad>#docker.okidoo.co/okidoo/codex-lb:74a911a5# /opt/codex-lb/docker-compose.yml'

ssh root@192.168.80.21 \
  'qm guest exec 124 -- docker compose -f /opt/codex-lb/docker-compose.yml up -d --no-deps codex-lb'
```

Known backups from the successful `a6c46d3b` deployment:

- Compose: `/opt/codex-lb/docker-compose.yml.backup-before-a6c46d3b-20260712133830`
- DB: `/opt/codex-lb/data/store.db.backup-before-a6c46d3b-20260712133830`

The production SQLite database had pre-existing integrity warnings around
request log indexes/fragmentation before the successful switch. Compare against
the active DB and older backups before blaming a new change.

### Validation Commands

Useful checks for this fork:

```sh
uv run python -m py_compile app/db/models.py app/main.py app/modules/chrome_debug/*.py
uv run ruff check app/db/models.py app/main.py app/modules/chrome_debug tests/integration/test_chrome_debug_bridge.py
uv run pytest tests/integration/test_chrome_debug_bridge.py tests/integration/test_accounts_api.py -q

cd frontend
bun run typecheck
bun run test src/features/chrome-debug/schemas.test.ts src/features/chrome-debug/hooks/use-chrome-debug.test.ts src/test/mocks/handler-coverage.test.ts
```

When touching frontend visual behavior, use browser verification before
finishing. For backend proxy/routing changes, add or update tests around model
selection and the OpenAI/Z.AI branch points.

### Security Notes

- Never commit real Z.AI, OpenAI, Codex-LB, Docker, or NPM credentials.
- There was once a real Z.AI key in a test fixture; it was replaced with a fake
  key. Keep tests using fake key material only.
- Chrome Debug is high-trust CDP access. Keep API-key grants explicit, tokens
  short-lived, audit events enabled, and browser registrations scoped to their
  owner key unless the user asks for broader sharing.

## Environment

- Python: .venv/bin/python (uv, CPython 3.13.3)
- GitHub auth for git/API is available via env vars: `GITHUB_USER`, `GITHUB_TOKEN` (PAT). Do not hardcode or commit tokens.
- For authenticated git over HTTPS in automation, use: `https://x-access-token:${GITHUB_TOKEN}@github.com/<owner>/<repo>.git`

## Code Conventions

The `/project-conventions` skill is auto-activated on code edits (PreToolUse guard).

| Convention | Location | When |
|-----------|----------|------|
| Code Conventions (Full) | `/project-conventions` skill | On code edit (auto-enforced) |
| Git Workflow | `.agents/conventions/git-workflow.md` | Commit / PR |

## Workflow (OpenSpec-first)

This repo uses **OpenSpec as the primary workflow and SSOT** for change-driven development.

### How to work (default)

1) Find the relevant spec(s) in `openspec/specs/**` and treat them as source-of-truth.
2) If the work changes behavior, requirements, contracts, or schema: create an OpenSpec change in `openspec/changes/**` first (proposal -> tasks).
3) Implement the tasks; keep code + specs in sync (update `spec.md` as needed).
4) Validate specs locally: `openspec validate --specs`
5) When done: verify + archive the change (do not archive unverified changes).

### Source of Truth

- **Specs/Design/Tasks (SSOT)**: `openspec/`
  - Active changes: `openspec/changes/<change>/`
  - Main specs: `openspec/specs/<capability>/spec.md`
  - Archived changes: `openspec/changes/archive/YYYY-MM-DD-<change>/`

## Documentation & Release Notes

- **Do not add/update feature or behavior documentation under `docs/`**. Use OpenSpec context docs under `openspec/specs/<capability>/context.md` (or change-level context under `openspec/changes/<change>/context.md`) as the SSOT.
- **Do not edit `CHANGELOG.md` directly.** Leave changelog updates to the release process; record change notes in OpenSpec artifacts instead.

### Documentation Model (Spec + Context)

- `spec.md` is the **normative SSOT** and should contain only testable requirements.
- Use `openspec/specs/<capability>/context.md` for **free-form context** (purpose, rationale, examples, ops notes).
- If context grows, split into `overview.md`, `rationale.md`, `examples.md`, or `ops.md` within the same capability folder.
- Change-level notes live in `openspec/changes/<change>/context.md` or `notes.md`, then **sync stable context** back into the main context docs.

Prompting cue (use when writing docs):
"Keep `spec.md` strictly for requirements. Add/update `context.md` with purpose, decisions, constraints, failure modes, and at least one concrete example."

### Commands (recommended)

- Start a change: `/opsx:new <kebab-case>`
- Create artifacts (step): `/opsx:continue <change>`
- Create artifacts (fast): `/opsx:ff <change>`
- Implement tasks: `/opsx:apply <change>`
- Verify before archive: `/opsx:verify <change>`
- Sync delta specs → main specs: `/opsx:sync <change>`
- Archive: `/opsx:archive <change>`

## Contributing & Merge Gates

When authoring or merging a PR (as a human contributor, a collaborator,
or an AI assistant acting on behalf of either), the binding workflow is
in [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md). The sections
an AI assistant most often needs are:

- [Merge gates](.github/CONTRIBUTING.md#merge-gates) — CI green +
  `@codex review` clean (or findings addressed) + `mergeable=CLEAN` +
  OpenSpec change folder for behavior changes + `Fixes #N` /
  `Closes #N` for issue cover.
- [Collaborator rules](.github/CONTRIBUTING.md#collaborator-rules) —
  no self-merge by default; large PRs get split (≈1-concern per PR,
  ~800 net lines / scoped capability ceiling).
- [Bus factor escape hatch](.github/CONTRIBUTING.md#bus-factor-escape-hatch)
  — self-merge allowed after **14 days** with all gates met and a
  comment invoking the clause.

An assistant preparing a merge MUST verify the gates against the
actual GitHub state (status check rollup, codex review submissions,
`mergeable` field) rather than asserting them from local history.
Local `uv run pytest` / `uv run ruff` / `codex review --base origin/main`
are encouraged but not substitutes for the cloud gates.

## PR Readiness / Review Trapdoors

These rules encode recurring review blockers observed across codex-lb PRs.

- OpenSpec is a hard gate for behavior, API, schema, CLI,
  dashboard-visible, proxy-routing, operator-contract, and compatibility
  changes. Create or update `openspec/changes/<slug>/` before coding, keep
  `spec.md` normative with MUST/SHALL-style requirements, put rationale and
  examples in `context.md` or change notes, and run strict OpenSpec validation
  before calling the PR ready. Code/tests alone are not enough when OpenSpec is
  required.
- Codex review state must come from current-head GitHub evidence. Check labels,
  latest Codex review/comment/reaction, and GraphQL review threads before using
  or claiming `🤖 codex: ok`. Usage-limit, environment, or missing-review
  results mean missing evidence, not approval. Unresolved non-outdated P-level
  Codex threads block readiness even when a top-level review comment looks
  clean.
- Proxy failover and retry patches must prove account ownership and settlement
  invariants. File-pinned requests must not cross accounts; API-key reservations
  must settle before error-health writes; excluded accounts must actually leave
  the selection loop; idle disconnects must not mark otherwise healthy accounts
  unhealthy; security/trusted-access routing must degrade only along the
  documented path.
- Async, fan-out, and session-lifecycle patches must prove task ownership and
  cleanup. Do not share one `AsyncSession` across concurrent tasks; cancel or
  await spawned tasks on failure; preserve finalization/settlement paths after
  partial errors; bound fan-out; and test partial-failure behavior, not only
  the all-success path.
- Database migrations must prove Alembic graph and data hygiene. New revisions
  must sit on the current intended parent with a single-head upgrade path, have
  downgrade/upgrade coverage where the project expects it, and include
  historical-row backfills or compatibility handling when new fields affect
  existing data.
- Issue-resolving PRs must name the exact `Fixes #N` / `Closes #N`, or state
  that they are partial. Keep PRs one concern wide. Revive stale work by making
  a focused branch on current `main`; do not drag an old broad/conflicted branch
  forward unless the maintainer explicitly wants that shape.
- Bug fixes need regression coverage at the externally failing product path:
  route, bridge, websocket, CLI, schema, dashboard UI, or migration path as
  applicable. Helper-only tests are not enough when the failing surface is
  elsewhere.
- Compatibility work must verify canonical and equivalent paths, trailing slash
  behavior, external error envelopes, env-var semantics, and response-schema
  contracts. Update OpenSpec/context and tests together so docs cannot promise
  behavior the code does not implement.
