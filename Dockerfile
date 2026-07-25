FROM ghcr.io/astral-sh/uv:python3.12-bookworm

LABEL org.opencontainers.image.title="Proof Agent development image"
LABEL org.opencontainers.image.production="false"

WORKDIR /app

COPY . .
RUN uv pip install --system -e ".[dev]"

CMD ["proof-agent", "demo"]
