# Stage 1: build the React front end on a standard glibc Node image (Vite 8 needs Node >= 22.12).
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# The Clerk publishable key is public by design. Railway passes service variables to ARGs of the same name.
ARG VITE_CLERK_PUBLISHABLE_KEY=""
ENV VITE_CLERK_PUBLISHABLE_KEY=$VITE_CLERK_PUBLISHABLE_KEY
RUN npm run build

# Stage 2: Python runtime with the built front end.
FROM python:3.12-slim AS run
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
# Safety net: make `uvicorn ... --port $PORT` work even when Railway runs it without a shell.
COPY docker/uvicorn-shim.sh /usr/local/bin/uvicorn
RUN chmod +x /usr/local/bin/uvicorn
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY entrypoint.sh ./entrypoint.sh
COPY --from=web /web/dist ./frontend/dist
RUN chmod +x /app/entrypoint.sh \
    && useradd --create-home --uid 10001 verbatim \
    && chown -R verbatim:verbatim /app /home/verbatim
# Uploaded/cleaned file bytes live in Postgres now (app/models.py: UploadedFile, CleanedFile), not on
# disk, so no persistent upload directory (and no volume) is needed - see docs/DECISIONS.md. Any scratch
# file this app writes for library compatibility (profiling a spreadsheet needs a real path) goes under
# the OS default temp directory (/tmp), which every container - and this non-root user - can always write
# to without a mkdir or chown of its own.
USER verbatim
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$PORT"]
