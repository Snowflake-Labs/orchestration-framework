FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

ENV UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --extra streamlit

COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra streamlit

FROM python:3.11-slim-bookworm

COPY --from=builder /app /app
RUN chmod -R 755 /app

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT []

CMD ["python", "-m", "streamlit", "run", "/app/demo_app/demo_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
