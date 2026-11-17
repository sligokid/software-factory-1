# runner-python: runner-base plus uv-managed CPython builds (no downloads at run time).
ARG BASE=software-factory/runner-base
FROM ${BASE}

USER root
RUN UV_PYTHON_BIN_DIR=/usr/local/bin uv python install 3.11 3.12 3.13 \
 && UV_PYTHON_BIN_DIR=/usr/local/bin uv python install --default --preview-features python-install-default 3.12 \
 && rm -rf /root/.cache
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PIP_DISABLE_PIP_VERSION_CHECK=1
USER agent
