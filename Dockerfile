FROM python:3.11-slim

WORKDIR /app

# Domestic PyPI mirror — the build node is on a China network where pypi.org
# is unreliable (see DECISIONS: single domestic cloud node).
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# Install the app and its runtime deps. Dev deps (pytest etc.) run on the host.
COPY pyproject.toml ./
COPY marketwind ./marketwind
COPY migrations ./migrations

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "marketwind.gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
