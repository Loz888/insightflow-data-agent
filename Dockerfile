FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANGSMITH_TRACING=false
WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN python -m pip install --no-cache-dir -r requirements.lock
COPY src ./src
COPY scripts ./scripts
COPY migrations ./migrations
COPY evaldata ./evaldata
RUN python -m pip install --no-deps . && useradd --create-home app && chown -R app:app /app
USER app
HEALTHCHECK --interval=10s --timeout=4s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready',timeout=3)"
CMD ["sh","scripts/container_start.sh"]
