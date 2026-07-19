FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite db + uploaded files live here; Fly mounts a persistent volume at /data.
ENV DATA_DIR=/data
EXPOSE 8080

# gunicorn serves the app factory. 2 workers is plenty for an internal tool;
# SQLite serializes writes, and WAL mode allows concurrent reads.
# --preload runs create_app() (schema init + migrations) once in the master
# before forking, so workers don't race to initialize the database.
CMD ["gunicorn", "-w", "2", "--preload", "-b", "0.0.0.0:8080", "app:create_app()"]
