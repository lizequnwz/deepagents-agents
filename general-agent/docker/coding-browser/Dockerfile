ARG CODING_BASE_IMAGE
FROM ${CODING_BASE_IMAGE}
ARG CODING_BASE_IMAGE

USER root
LABEL io.general-agent.coding-browser="playwright-1.63.0"
LABEL io.general-agent.coding-base-image="${CODING_BASE_IMAGE}"

RUN python -I -m pip --isolated --disable-pip-version-check --no-cache-dir install \
      --only-binary=:all: --target /opt/general-agent/browser-sdk playwright==1.63.0 \
    && PYTHONPATH=/opt/general-agent/browser-sdk \
      PLAYWRIGHT_BROWSERS_PATH=/opt/general-agent/browsers \
      python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY general_agent/coding/browser_controller.py /opt/general-agent/browser_controller.py

USER 1000:1000
