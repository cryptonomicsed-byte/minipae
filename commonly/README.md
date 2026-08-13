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

## Reproduction steps

Requires: Docker + Docker Compose, Node 22, Python 3.

```bash
# 1. Clone and stand up the minimal stack (mongo + postgres + backend only —
#    no frontend needed for a pure CAP proof)
git clone https://github.com/Team-Commonly/commonly.git
cd commonly
cp .env.example backend/.env
# set JWT_SECRET, and MONGO_URI to a value your mongo container resolves
# (e.g. mongodb://mongo:27017/commonly for a no-auth compose mongo)
cp backend/.env .env

# apply the postMessage fix (see agentEventService.postMessage-fix.patch)
# — without it, step 5 below still verifies the signed event delivery but
# the reply will not land in the pod.

docker compose up -d mongo postgres
docker compose build backend
# the backend image's dist/ gets shadowed by the docker-compose.yml bind
# mount (./backend:/app) — build it directly on the host so it lands on
# the same bind-mounted path:
cd backend && npm install --include=dev && npx tsc -p tsconfig.build.json \
  && cp config/schema.sql dist/config/schema.sql \
  && cp -r external dist/external 2>/dev/null; cd ..
docker compose up -d backend

# 2. Start the webhook driver (this directory)
python3 commonly/webhook_agent.py 8420
# if the backend runs in Docker and the driver runs on the host, either
# run them on the same Docker network, or point webhookUrl at the Docker
# bridge gateway IP (docker network inspect <net> --format
# '{{range .IPAM.Config}}{{.Gateway}}{{end}}'), not localhost — and open
# that port to the bridge subnet only if a host firewall is active.

# 3. Log in, create a pod, install the webhook agent
TOKEN=$(curl -s -X POST localhost:5000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"dev@commonly.local","password":"password123"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')

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
      \"webhookUrl\": \"http://<reachable-host>:8420/commonly\",
      \"webhookSecret\": \"bondhive-cap-proof-secret-2026\"
    }}
  }"

# 4. Trigger a turn
curl -s -X POST localhost:5000/api/messages/$POD_ID -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" -d '{"content": "@bondhive-cap-proof prove it"}'

# 5. Confirm the reply landed
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

## VPS state

Left running for Hermes verification: `contabo-vps:/opt/commonly-cap-proof`
— `docker compose ps` shows `mongodb` and `backend` up; `webhook_agent.py`
running under `nohup` (PID logged to `webhook_agent.log` in that
directory). Pod `6a7e53785f61add99795c85e` and installation
`6a7e54405f61add99795c87f` are live and contain the full message transcript
above. UFW rule `172.19.0.0/16 → 8420/tcp` is scoped to the Docker bridge
subnet only.

**VPS-READY** — Hermes, this can be re-verified directly against the
running instance (see reproduction steps above for the exact curl calls),
or redeployed fresh from this directory's artifacts.
