# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: runtime
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bullseye

# Don't leave pip cache sitting around
ENV PIP_NO_CACHE_DIR=1

# Set work dir
WORKDIR /app

# Copy only the requirements first (so this layer is cached until you actually change reqs)
COPY requirements.txt .

# Install Python deps
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of your app
COPY . .

# Copy & make your entrypoint executable
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create any runtime dirs in one command
RUN mkdir -p /app/data/databases /app/data/logs

ENTRYPOINT ["/entrypoint.sh"]
