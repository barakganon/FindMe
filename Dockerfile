# Stage 1: Build
FROM python:3.11-slim AS builder

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Install runtime system dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
COPY . .

ENV PATH=/root/.local/bin:$PATH

# Install Playwright browsers (browser binaries only — system deps installed manually above
# because --with-deps fails on Debian Bookworm: ttf-unifont and ttf-ubuntu-font-family
# were removed/renamed and Playwright's installer hasn't caught up).
RUN playwright install chromium

# Use a shell entrypoint so Render's injected $PORT is honored at runtime.
# Falls back to 8000 in local Docker / docker-compose.
CMD ["sh", "scripts/start.sh"]
