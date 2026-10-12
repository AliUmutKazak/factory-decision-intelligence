FROM python:3.11-slim

# Sistem bagimliliklari ve derleme araclari
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ARG FACTORY_BUILD_GIT_SHA=UNKNOWN
ENV FACTORY_BUILD_GIT_SHA=${FACTORY_BUILD_GIT_SHA}
LABEL org.opencontainers.image.revision=${FACTORY_BUILD_GIT_SHA}

# GitHub runner's bind-mounted runtime directories use UID 1001. Keep the
# demo services unprivileged after installing system and Python packages.
RUN groupadd --gid 1001 fdi && useradd --uid 1001 --gid fdi --create-home fdi

# Paket bagimliliklarini kopyala ve yukle
COPY requirements-linux.lock .
RUN pip install --no-cache-dir -r requirements-linux.lock

# Proje kaynak kodunu kopyala
COPY --chown=fdi:fdi . .
RUN mkdir -p /app/runs /app/staging && chown -R fdi:fdi /app
USER fdi

# Varsayilan portlar (FastAPI: 8000, Streamlit: 8501)
EXPOSE 8000 8501

# Baslangic komutu (FastAPI servisini baslatir)
CMD ["uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
