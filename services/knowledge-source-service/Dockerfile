FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/knowledge-source-service
COPY pyproject.toml ./
COPY knowledge_source_service ./knowledge_source_service
RUN python -m pip install --disable-pip-version-check .

RUN useradd --create-home --uid 10001 knowledge-service
USER 10001:10001

EXPOSE 8080
ENTRYPOINT ["knowledge-source-service"]
CMD ["api"]
