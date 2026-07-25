# syntax=docker/dockerfile:1.7

# Supply immutable name@sha256 references from the candidate build workflow.
ARG NODE_IMAGE
ARG UV_IMAGE
ARG RUNTIME_IMAGE

FROM ${NODE_IMAGE} AS frontend-build
WORKDIR /src
COPY package.json package-lock.json ./
COPY packages/ui/package.json packages/ui/package.json
COPY dashboard/package.json dashboard/package.json
COPY chat/package.json chat/package.json
RUN npm ci
COPY packages/ui packages/ui
COPY dashboard dashboard
COPY chat chat
RUN npm run build

FROM ${UV_IMAGE} AS python-build
WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
COPY proof_agent proof_agent
COPY examples/agent_management_insurance_specialist examples/agent_management_insurance_specialist
RUN uv build --wheel --sdist
RUN uv venv /opt/proofagent/venv
RUN uv pip install \
    --python /opt/proofagent/venv/bin/python \
    --no-cache \
    "$(find dist -name 'proof_agent-*.whl' -type f -print -quit)[production]"

FROM ${RUNTIME_IMAGE} AS runtime
LABEL org.opencontainers.image.title="Proof Agent production image"
LABEL org.opencontainers.image.production="true"

ENV PATH="/opt/proofagent/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROOF_AGENT_MODE=production

RUN groupadd --gid 10001 proofagent \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent proofagent \
    && mkdir -p /opt/proofagent/static/dashboard /opt/proofagent/static/operator-chat \
    && chown -R 10001:10001 /opt/proofagent

COPY --from=python-build --chown=10001:10001 /opt/proofagent/venv /opt/proofagent/venv
COPY --from=frontend-build --chown=10001:10001 /src/dashboard/dist /opt/proofagent/static/dashboard
COPY --from=frontend-build --chown=10001:10001 /src/chat/dist /opt/proofagent/static/operator-chat

WORKDIR /opt/proofagent
USER 10001:10001
EXPOSE 8000
CMD ["proof-agent", "server", "--host", "0.0.0.0", "--port", "8000", "--no-seed-example-agent"]
