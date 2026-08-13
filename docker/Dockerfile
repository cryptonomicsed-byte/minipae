# GenTeam Local Computer daemon — hardened container
# Build:  docker build -t genteam-daemon:0.13.0 .
# Run:    see run_genteam.sh (cap-drop ALL, resource caps, named volume, no host mounts)
FROM node:22-slim

# minimal runtime deps for the driver CLIs (codex + claude-code are npm packages)
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# install the daemon + both driver CLIs (codex preferred, claude as fallback)
RUN npm install -g @genspark/genteam-daemon@stable \
 && npm install -g @openai/codex @anthropic-ai/claude-code \
 && npm cache clean --force

# non-root runtime user; state lives in the named volume at /home/genteam
RUN useradd -m -s /bin/bash genteam \
 && mkdir -p /home/genteam/.genteam \
 && chown -R genteam:genteam /home/genteam

USER genteam
WORKDIR /home/genteam

ENV GENTEAM_HOME=/home/genteam/.genteam

# entrypoint resolves the actual bin path
ENTRYPOINT ["/usr/local/bin/genteam-daemon"]
