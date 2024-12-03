FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1

ENV UV_LINK_MODE=copy

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --extra streamlit

ADD . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra streamlit

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT []

CMD ["python", "-m", "streamlit", "run", "demo_app/demo_app.py", "--server.port=8510", "--server.address=0.0.0.0"]
