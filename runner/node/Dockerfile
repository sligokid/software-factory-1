# runner-node: runner-base plus Node.js LTS; pnpm and yarn through corepack (version from the
# product's packageManager field, fetched from the npm registry the product allows in egress).
ARG BASE=software-factory/runner-base
FROM ${BASE}

ARG NODE_VERSION=24.22.3
USER root
RUN arch="$(dpkg --print-architecture | sed 's/amd64/x64/')" \
 && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${arch}.tar.xz" \
      | tar -xJ -C /usr/local --strip-components=1 --no-same-owner \
          --exclude='*/CHANGELOG.md' --exclude='*/README.md' --exclude='*/LICENSE' --exclude='*/share' \
 && corepack enable pnpm yarn \
 && node --version && npm --version
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    NPM_CONFIG_UPDATE_NOTIFIER=false
USER agent
