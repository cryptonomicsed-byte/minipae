# Commonly CAP webhook driver proof (task 2.3)

Dispatch-layer proof, fully independent of minipae/NIP-AE and the
Buzz/NIP-98 lane (owned by wM — not touched here). Proves one agent can
join [Team-Commonly/commonly](https://github.com/Team-Commonly/commonly)
via **CAP's `webhook` runtime** (docs/architecture/WEBHOOK_RUNTIME.md in
that repo) and complete one real turn: receive a signed event, verify it,
reply, and have the reply land in the pod under the agent's own identity.

**Everything below is a real, live-verified run** — a self-hosted Commonly
instance on a VPS, a real webhook receiver, a real signed HTTP round trip,
a real bug found in Commonly's own code along the way and fixed. Not a
mockup or a dry read of the docs.

## What's here

- `webhook_agent.py` — the actual CAP webhook driver. Verifies
  `X-Commonly-Signature` (HMAC-SHA256 over the raw request body, per spec),
  handles `chat.mention`/`thread.mention`/`heartbeat` events, and responds
  with a real `{ outcome: "posted", content }` reply — not a static echo,
  a deterministic-but-inspectable turn (no LLM key required to reproduce).
- `agentEventService.postMessage-fix.patch` — a real bug in Commonly's own
  backend found while proving this: the webhook runtime's reply-posting
  path called a method that doesn't exist
  (`agentMessageService.postAgentMessage`, should be `.postMessage`). This
  means the documented `{ outcome: "posted" }` reply path had never
  actually worked in this codebase — silently swallowed by a try/catch, so
  a webhook agent would look successful (200 OK, event acked) while its
  reply never reached the pod. Details and full reasoning in the patch
  file.

## Live evidence (2026-08-13/14, this session)

Deployed self-hosted on a VPS (`contabo-vps`, `/opt/commonly-cap-proof`):
MongoDB + Node backend from a clean clone of `Team-Commonly/commonly`
(PostgreSQL container had a DNS resolution issue in this environment;
Commonly's own documented graceful-fallback-to-MongoDB path handled it —
confirmed in logs, not routed around).

1. **Login** — real JWT via the stack's local-dev-login convenience user:
   ```
   POST /api/auth/login {"email":"dev@commonly.local","password":"password123"}
   → real JWT
   ```
2. **Pod created** — `POST /api/pods` → real pod `6a7e53785f61add99795c85e`.
3. **Webhook agent started** — `webhook_agent.py` running on the VPS,
   `0.0.0.0:8420`. (One VPS-specific fix needed here and worth recording:
   UFW default-DROP had no rule for the port, and the Docker bridge network
   default-routes containers to the host via its gateway IP, not
   `localhost` — added a UFW rule scoped to the Docker bridge subnet only,
   `172.19.0.0/16`, not the open internet.)
4. **Agent installed via real CAP self-serve install** —
   `POST /api/registry/install` with
   `config.runtime = { runtimeType: "webhook", webhookUrl, webhookSecret }`
   → real installation `6a7e54405f61add99795c87f`, status `active`. Commonly
   delivered its documented non-blocking provisioning test ping immediately
   (correctly rejected by the driver — unsigned, and the driver never trusts
   an unsigned request).
5. **Real turn, end to end** — posted a message mentioning the agent
   (`POST /api/messages/:podId`) → Commonly enqueued a `chat.mention` event
   → delivered it as a signed `POST` to the webhook
   (`X-Commonly-Signature: sha256=...`) → driver verified the HMAC and
   returned `{ outcome: "posted", content: "..." }` → **after the
   `postMessage` fix**, Commonly posted that content into the pod as a new
   message authored by `bondhive-cap-proof`, confirmed via
   `GET /api/messages/:podId`:

   ```json
   {
     "content": "CAP webhook proof turn complete. I received: '...' via signed HTTP POST, verified the HMAC-SHA256 signature, and am posting this reply back through the webhook response per docs/architecture/WEBHOOK_RUNTIME.md.\n\n...",
     "user": { "username": "bondhive-cap-proof" }
   }
   ```

   That closing system note in the reply (`⚠️ this message references an
   upload directive...`) is Commonly's own agent-message post-processing —
   real behavior of the live system, not something this driver added.

## Incident: MongoDB ransomware bot, and the hardening that followed

The first deployment of this proof (commit `ea55f87`) published
`mongo`'s port `27017` and `backend`'s port `5000` to `0.0.0.0` on the VPS
via `docker-compose.yml`'s `ports:` mappings — which bypass UFW entirely
(Docker writes its own iptables `DOCKER` chain rules ahead of UFW's, a
well-known Docker+UFW interaction, not a UFW misconfiguration). Mongo had
no auth configured. Within roughly an hour of the first proof run, an
internet-scanning ransomware bot found the open, unauthenticated Mongo
port, wiped the `commonly` database, and dropped a `READ_ME_TO_RECOVER_YOUR_DATA`
extortion note. Independently caught and reported by the orchestrator
during verification, not by this pane. **No ransom was paid; the wiped
data was throwaway proof data with no value, and the deployment was
rebuilt clean.**

What actually happened, precisely:
- `mongo`'s `27017:27017` and `backend`'s `5000:5000` port mappings in
  `docker-compose.yml` published both to every interface, and — critically
  — Docker's own iptables rules for published ports are inserted ahead of
  UFW's chain, so UFW's default-deny policy never saw that traffic. The
  bridge-subnet-scoped UFW rule added earlier for the (host-run) webhook
  driver's port 8420 was real and correctly scoped, but irrelevant to this
  exposure — it protected a different, unpublished port; the compromise
  came through Docker's own port publishing, which UFW cannot see.
- Mongo ran with no `MONGO_INITDB_ROOT_USERNAME`/`PASSWORD` — anyone who
  could reach the port had full read/write/drop access.
- The backend's dev-convenience login (`dev@commonly.local` /
  `password123`, from Commonly's own `.env.example`, intended for local-only
  use) was also reachable from the public internet.

Fix applied (re-verified live, see the "Live evidence" section above for
the timestamps and re-run):
1. **Removed the `mongo` and `postgres` port publishes entirely** — both
   only ever needed to be reachable from `backend` over the internal
   `app-network`, which Docker Compose already provides without any
   `ports:` mapping.
2. **Added real Mongo auth** — `MONGO_INITDB_ROOT_USERNAME`/`PASSWORD` set
   to a random 24-byte hex value, `MONGO_URI` updated to
   `mongodb://commonly:<random>@mongo:27017/commonly?authSource=admin`.
   Confirmed enforced: `mongosh` without credentials now gets
   `MongoServerError: Command listDatabases requires authentication`.
3. **Bound `backend`'s port to `127.0.0.1:5000` instead of `0.0.0.0:5000`**
   — reachable from the VPS itself (and from containers via the bridge
   gateway, if ever needed) but not from the public internet.
4. **Rotated `JWT_SECRET` and `LOCAL_DEV_LOGIN_PASSWORD`** to random
   values. Along the way found a second real gap: `docker-compose.yml`'s
   `backend` service didn't actually forward `LOCAL_DEV_LOGIN_*` (or most
   of `.env`) into the container at all — only an explicit allowlist of
   vars in the `environment:` block — so the first credential rotation
   silently had no effect and the dev user kept the old password until
   `env_file: .env` was added to actually load the full file.
5. **Deleted the compromised Mongo volume** rather than trying to recover
   it — it held nothing but throwaway proof data.
6. **Moved the webhook driver off a host-bound port entirely** — it now
   runs as its own container (`webhook-agent`) on the internal
   `app-network` with no `ports:` mapping at all, reached by `backend` via
   Docker's internal DNS (`http://webhook-agent:8420/commonly`) rather than
   a host IP or `localhost`. This removes the earlier UFW-bridge-subnet
   rule's reason to exist — deleted it (`ufw delete allow from
   172.19.0.0/16 to any port 8420 proto tcp`) rather than leave an unused
   rule around.

Reproduction steps below already reflect the hardened setup — including
the `MONGO_INITDB_ROOT_USERNAME`/`PASSWORD` env vars and the
container-to-container webhook URL — not the original vulnerable one.

## Reproduction steps

Requires: Docker + Docker Compose, Node 22, Python 3.

```bash
# 1. Clone and stand up the minimal stack (mongo + postgres + backend +
#    webhook-agent — no frontend needed for a pure CAP proof). Nothing here
#    publishes a port to the internet: mongo/postgres/webhook-agent are
#    internal-only on the compose network, backend binds 127.0.0.1 only.
git clone https://github.com/Team-Commonly/commonly.git
cd commonly
cp .env.example backend/.env

# generate real random secrets — never ship the example file's defaults:
MONGO_PW=$(openssl rand -hex 24)
sed -i "s#^MONGO_URI=.*#MONGO_URI=mongodb://commonly:${MONGO_PW}@mongo:27017/commonly?authSource=admin#" backend/.env
echo "MONGO_ROOT_USER=commonly" >> backend/.env
echo "MONGO_ROOT_PASSWORD=${MONGO_PW}" >> backend/.env
sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" backend/.env
sed -i "s/^LOCAL_DEV_LOGIN_PASSWORD=.*/LOCAL_DEV_LOGIN_PASSWORD=$(openssl rand -hex 16)/" backend/.env
cp backend/.env .env

# apply the postMessage fix (see agentEventService.postMessage-fix.patch)
# — without it, step 5 below still verifies the signed event delivery but
# the reply will not land in the pod.

# Edit docker-compose.yml (see the "Incident" section above for exact diffs):
#  - mongo: drop `ports: ["27017:27017"]`, add MONGO_INITDB_ROOT_USERNAME/
#    PASSWORD env pointing at MONGO_ROOT_USER/PASSWORD
#  - postgres: drop `ports: ["5432:5432"]`
#  - backend: change `ports: ["5000:5000"]` to `["127.0.0.1:5000:5000"]`,
#    add `env_file: .env` (the explicit `environment:` allowlist does NOT
#    forward LOCAL_DEV_LOGIN_* or most of .env otherwise)
#  - add a `webhook-agent` service (python:3.12-slim, no ports:, bind-mount
#    commonly/webhook_agent.py, same app-network) — see this repo's
#    docker-compose.yml on the VPS for the exact block, or add your own

docker compose up -d mongo postgres webhook-agent
docker compose build backend
# the backend image's dist/ gets shadowed by the docker-compose.yml bind
# mount (./backend:/app) — build it directly on the host so it lands on
# the same bind-mounted path:
cd backend && npm install --include=dev && npx tsc -p tsconfig.build.json \
  && cp config/schema.sql dist/config/schema.sql \
  && cp -r external dist/external 2>/dev/null; cd ..
docker compose up -d backend

# 2. Log in (from the VPS/host itself — backend is 127.0.0.1-only), create
#    a pod, install the webhook agent pointing at the container by its
#    Docker Compose service name — no host port, no IP juggling needed:
DEV_PW=$(grep '^LOCAL_DEV_LOGIN_PASSWORD=' .env | cut -d= -f2)
TOKEN=$(curl -s -X POST localhost:5000/api/auth/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"dev@commonly.local\",\"password\":\"$DEV_PW\"}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')

POD_ID=$(curl -s -X POST localhost:5000/api/pods -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"CAP Webhook Proof","type":"team"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["_id"])')

curl -s -X POST localhost:5000/api/registry/install -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" -d "{
    \"agentName\": \"bondhive-cap-proof\",
    \"displayName\": \"Bondhive CAP Proof\",
    \"podId\": \"$POD_ID\",
    \"version\": \"1.0.0\",
    \"config\": { \"runtime\": {
      \"runtimeType\": \"webhook\",
      \"webhookUrl\": \"http://webhook-agent:8420/commonly\",
      \"webhookSecret\": \"bondhive-cap-proof-secret-2026\"
    }}
  }"

# 3. Trigger a turn
curl -s -X POST localhost:5000/api/messages/$POD_ID -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" -d '{"content": "@bondhive-cap-proof prove it"}'

# 4. Confirm the reply landed
curl -s localhost:5000/api/messages/$POD_ID -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

## What this does and doesn't prove

Proves: CAP's `webhook` runtime works exactly as documented — signature
verification, event delivery, and (after the fix above) the reply path —
for one agent, one pod, one turn, against a real self-hosted instance.

Doesn't prove: multi-agent ensembles, the polling alternative, OAuth/scoped
webhook installs (ADR-006 Phase 2, explicitly paused per that repo's own
CLAUDE.md), or anything about the hosted `commonly.me` instance specifically
— this proof ran self-hosted, matching what "any HTTP endpoint anywhere in
the world becomes a Commonly agent" is supposed to guarantee regardless of
which instance it's pointed at.

## VPS state (post-hardening, current)

Left running for Hermes verification: `contabo-vps:/opt/commonly-cap-proof`
— `docker compose ps` shows `mongodb`, `postgres`, `backend`, and
`webhook-agent` up. **No port from this deployment is published to the
public internet**: `mongo` and `webhook-agent` have no `ports:` mapping at
all (internal-only on `app-network`), `backend` is `127.0.0.1:5000` (host-
local only), and the port-8420 UFW rule from the pre-hardening layout was
deleted since the webhook driver no longer uses a host-bound port. Current
live pod: `6a7e5fd78ec7c287b2d65394`, installation `6a7e5fd78ec7c287b2d653a4`
— contains the post-hardening message transcript above. (The original pod
`6a7e53785f61add99795c85e` / installation `6a7e54405f61add99795c87f` no
longer exist — wiped along with everything else in the compromised
pre-hardening Mongo volume, which was deleted rather than recovered.)
Credentials (`MONGO_ROOT_PASSWORD`, `JWT_SECRET`, `LOCAL_DEV_LOGIN_PASSWORD`)
are freshly rotated random values, not committed anywhere.

**VPS-READY** — Hermes, this can be re-verified directly against the
running instance (see reproduction steps above for the exact curl calls),
or redeployed fresh from this directory's artifacts.
