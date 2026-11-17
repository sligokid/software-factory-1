# runner-base: Claude Code, Spec Kit, git, gh and the factory runner (entrypoint + egress proxy).
# Build from the repo root with `make images` (versions come from src/factory/__init__.py).
FROM debian:bookworm-slim

ARG CLAUDE_CODE_VERSION
ARG SPECKIT_VERSION
ARG UV_VERSION=0.13.9

RUN apt-get update \
 && apt-get install -y --no-install-recommends bash ca-certificates curl gh git jq procps xz-utils \
 && rm -rf /var/lib/apt/lists/*

# uv-managed Python for Spec Kit and the factory runner, installed outside any home directory.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python
RUN curl -fsSL "https://astral.sh/uv/${UV_VERSION}/install.sh" \
      | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh \
 && UV_TOOL_DIR=/opt/uv/tools UV_TOOL_BIN_DIR=/usr/local/bin \
      uv tool install --python 3.12 "specify-cli==${SPECKIT_VERSION}" \
 && rm -rf /root/.cache

COPY pyproject.toml uv.lock README.md /tmp/factory/
COPY src /tmp/factory/src
RUN UV_TOOL_DIR=/opt/uv/tools UV_TOOL_BIN_DIR=/usr/local/bin \
      uv tool install --python 3.12 /tmp/factory \
 && rm -rf /tmp/factory /root/.cache

# Claude Code native build, pinned; the binary is copied out of root's home.
RUN curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_CODE_VERSION}" \
 && install -m 0755 "$(readlink -f /root/.local/bin/claude)" /usr/local/bin/claude \
 && rm -rf /root/.local /root/.claude /root/.claude.json /root/.cache

# Non-root agent. /workspace and /home/agent become per-run anonymous volumes.
RUN useradd --uid 10001 --user-group --create-home --home-dir /home/agent --shell /bin/bash agent \
 && mkdir /workspace && chown agent:agent /workspace

ENV HOME=/home/agent \
    FACTORY_WORKSPACE=/workspace \
    DISABLE_AUTOUPDATER=1 \
    DISABLE_TELEMETRY=1 \
    DISABLE_ERROR_REPORTING=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    GIT_TERMINAL_PROMPT=0

USER agent
WORKDIR /workspace
ENTRYPOINT ["factory-runner"]
