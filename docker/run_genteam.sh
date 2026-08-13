#!/bin/bash
# Hardened launcher for the GenTeam daemon container on the VPS.
# Usage:
#   GENTEAM_KEY=gtm_... bash run_genteam.sh
#   GENTEAM_KEY=... ANTHROPIC_API_KEY=sk-ant-... bash run_genteam.sh   (claude driver)
#   GENTEAM_KEY=... OPENAI_API_KEY=sk-... bash run_genteam.sh          (codex driver)
#
# Driver auth: set ANTHROPIC_API_KEY and/or OPENAI_API_KEY in the env when
# launching — the daemon passes process.env through to driver processes, so
# claude/codex authenticate via env without any interactive login.
#
# Hardening:
#   --cap-drop ALL            no kernel capabilities at all
#   --security-opt no-new-privileges
#   --memory 2g --cpus 1      resource caps (VPS has 2 cores / 7.8G)
#   --pids-limit 256          fork-bomb guard
#   --read-only + tmpfs       immutable rootfs, writable tmp only
#   --user genteam            non-root inside
#   named volume gtstate      daemon state + driver auth persist here ONLY —
#                             never mounted to /opt/ares or host paths
set -euo pipefail

KEY="${GENTEAM_KEY:-${1:-}}"
if [ -z "$KEY" ]; then
  echo "usage: GENTEAM_KEY=gtm_... bash run_genteam.sh   (or pass key as \$1)" >&2
  exit 2
fi

IMAGE="genteam-daemon:0.13.0"
NAME="genteam-daemon"
VOL="gtstate"

docker rm -f "$NAME" >/dev/null 2>&1 || true

# build -e flags for driver API keys (only pass what's provided)
ENVFLAGS=()
[ -n "${ANTHROPIC_API_KEY:-}" ] && ENVFLAGS+=(-e "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")
[ -n "${OPENAI_API_KEY:-}" ] && ENVFLAGS+=(-e "OPENAI_API_KEY=$OPENAI_API_KEY")

docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --memory 2g \
  --cpus 1 \
  --pids-limit 256 \
  --read-only \
  --tmpfs /tmp:rw,size=128m \
  --tmpfs /home/genteam/.cache:rw,size=64m \
  --volume "$VOL:/home/genteam" \
  --user genteam \
  "${ENVFLAGS[@]}" \
  "$IMAGE" \
  --server-url https://www.genspark.ai \
  --api-key "$KEY"

echo "container $NAME started (state volume: $VOL)"
echo "driver keys: ANTHROPIC=${ANTHROPIC_API_KEY:+set} OPENAI=${OPENAI_API_KEY:+set}"
echo "logs:  docker logs -f $NAME"
echo "shell: docker exec -it $NAME bash"
