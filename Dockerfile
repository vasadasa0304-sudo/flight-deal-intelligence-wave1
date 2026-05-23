FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy dependency spec first so this layer is only invalidated when deps change.
COPY pyproject.toml README.md ./
RUN mkdir -p src && \
    python -m pip install --upgrade pip --no-cache-dir && \
    python -m pip install --no-cache-dir -e ".[dev]"

# Copy sources after deps — only invalidated when code changes, not on dep changes.
COPY src ./src
COPY app ./app
COPY scripts ./scripts
COPY migrations ./migrations

EXPOSE 8501

CMD ["python", "-m", "streamlit", "run", "app/streamlit_app.py", \
     "--server.address=0.0.0.0", "--server.headless=true"]
