FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/doculens
COPY backend/ ./backend/
RUN pip install --no-cache-dir ./backend && useradd --create-home doculens
COPY --from=frontend /build/dist ./frontend/dist
# Model files are not baked into the image. Mount them here; the semantic model
# is read from /opt/doculens/models/semantic. Hosts and origins are supplied at
# run time, e.g. -e DOCULENS_ALLOWED_HOSTS='["scanner.example"]'.
VOLUME /opt/doculens/models
WORKDIR /opt/doculens/backend
USER doculens
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
