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
WORKDIR /opt/doculens/backend
USER doculens
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
