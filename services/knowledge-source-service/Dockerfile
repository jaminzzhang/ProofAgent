# syntax=docker/dockerfile:1.7

# Supply immutable name@sha256 references from the candidate build workflow.
ARG UV_IMAGE
ARG RUNTIME_IMAGE

FROM ${UV_IMAGE} AS python-build
WORKDIR /src
ENV UV_PROJECT_ENVIRONMENT=/opt/knowledge-source-service/venv
COPY pyproject.toml uv.lock ./
COPY knowledge_source_service ./knowledge_source_service
RUN uv sync --frozen --no-dev --no-editable

FROM ${RUNTIME_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/knowledge-source-service/venv/bin:${PATH}"

WORKDIR /opt/knowledge-source-service
COPY --from=python-build --chown=10001:10001 \
    /opt/knowledge-source-service/venv /opt/knowledge-source-service/venv

RUN groupadd --gid 10001 knowledge-service \
    && useradd --uid 10001 --gid 10001 --no-create-home \
        --home-dir /nonexistent knowledge-service
USER 10001

EXPOSE 8080
ENTRYPOINT ["knowledge-source-service"]
CMD ["api"]
