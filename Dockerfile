FROM node:20-bookworm-slim AS wa-deps

WORKDIR /build/wa_service
COPY wa_service/package.json wa_service/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund


FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

# Baileys only needs the Node runtime. Its dependencies are built once in the
# first stage instead of being downloaded again whenever Railway restarts.
COPY --from=wa-deps /usr/local/bin/node /usr/local/bin/node

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY wa_service/package.json wa_service/package-lock.json ./wa_service/
COPY --from=wa-deps /build/wa_service/node_modules ./wa_service/node_modules
COPY . .

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port \"${PORT:-8080}\" --workers 1"]
