FROM node:24-alpine AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FINESSE_ENV=production
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY engine/ ./engine/
COPY run.py ./
COPY --from=frontend-build /src/engine/web/react-ui/ ./engine/web/react-ui/
RUN groupadd --system finesse && useradd --system --gid finesse --home-dir /nonexistent finesse \
    && mkdir -p /app/data /app/vault \
    && chown -R finesse:finesse /app
USER finesse:finesse
EXPOSE 8600
CMD ["python", "run.py"]
