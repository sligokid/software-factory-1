# runner-reviewer: runner-base plus Playwright and Chromium for `factory screenshots`.
ARG BASE=software-factory/runner-base
FROM ${BASE}

ARG PLAYWRIGHT_VERSION
USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
 && uv pip install --python /opt/uv/tools/software-factory/bin/python "playwright==${PLAYWRIGHT_VERSION}" \
 && /opt/uv/tools/software-factory/bin/playwright install --with-deps chromium \
 && rm -rf /root/.cache /var/lib/apt/lists/*
USER agent
