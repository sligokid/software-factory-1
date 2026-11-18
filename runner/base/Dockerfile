# runner-base: Claude Code, Spec Kit, git, gh, the factory CLI (runner entrypoint, egress proxy,
# `factory ci`) and the CI scanners: gitleaks, semgrep, osv-scanner.
# Build from the repo root with `make images` (versions come from src/factory/__init__.py).
FROM debian:bookworm-slim

ARG CLAUDE_CODE_VERSION
ARG SPECKIT_VERSION
ARG GITLEAKS_VERSION
ARG OSV_SCANNER_VERSION
ARG SEMGREP_VERSION
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

# CI scanners (language-agnostic): secrets, SAST, dependency vulnerabilities.
RUN arch="$(dpkg --print-architecture)" \
 && gl_arch="$([ "$arch" = amd64 ] && echo x64 || echo "$arch")" \
 && curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${gl_arch}.tar.gz" \
      | tar -xz -C /usr/local/bin gitleaks \
 && curl -fsSL -o /usr/local/bin/osv-scanner \
      "https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_linux_${arch}" \
 && chmod 0755 /usr/local/bin/osv-scanner \
 && UV_TOOL_DIR=/opt/uv/tools UV_TOOL_BIN_DIR=/usr/local/bin \
      uv tool install --python 3.12 "semgrep==${SEMGREP_VERSION}" \
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

# Build and test leftovers stay out of agent commits even when a product has no .gitignore
# (untracked files only; the product's own .gitignore and tracked files are unaffected).
RUN printf '%s\n' __pycache__/ '*.py[cod]' .pytest_cache/ .mypy_cache/ .ruff_cache/ .venv/ \
      node_modules/ > /etc/gitignore \
 && git config --system core.excludesFile /etc/gitignore

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
