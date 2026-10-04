FROM node:22-bookworm-slim AS node
FROM ghcr.io/astral-sh/uv:0.11.28 AS uv
FROM python:3.11-slim-bookworm

LABEL io.general-agent.coding-runtime="3"
LABEL io.general-agent.coding-typescript="5.9.3"

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install --prefix /opt/general-agent/typescript-sdk --ignore-scripts --no-audit --no-fund \
         --registry=https://registry.npmjs.org --userconfig=/dev/null --globalconfig=/dev/null typescript@5.9.3 \
    && mkdir -p /opt/general-agent /work \
    && rmdir /tmp \
    && ln -s /work/tmp /tmp \
    && ln -s /work/repo /repo \
    && python --version \
    && node --version \
    && npm --version \
    && uv --version

COPY general_agent/processes.py /opt/general-agent/processes.py
COPY general_agent/coding/runtime_controller.py /opt/general-agent/controller.py
COPY general_agent/coding/setup_controller.py /opt/general-agent/setup_controller.py
COPY general_agent/coding/typescript_controller.cjs /opt/general-agent/typescript_controller.cjs

USER 1000:1000
ENTRYPOINT ["/usr/local/bin/python", "-I", "/opt/general-agent/controller.py"]
CMD ["idle"]
