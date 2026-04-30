#!/bin/bash
# Run once on a fresh Ubuntu 22.04 EC2 instance
set -e

# Update and install basic dependencies
sudo apt-get update
sudo apt-get install -y \
    curl \
    git \
    build-essential \
    software-properties-common

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
sudo systemctl enable docker
sudo systemctl start docker

# Install Docker Compose
sudo apt-get install -y docker-compose-plugin

# Install nginx + certbot
sudo apt-get install -y nginx certbot python3-certbot-nginx

# Clone repo
sudo mkdir -p /opt/findme
sudo chown ubuntu:ubuntu /opt/findme
if [ ! -d "/opt/findme/.git" ]; then
    git clone https://github.com/barakganon/FindMe.git /opt/findme
fi
cd /opt/findme

# Create .env from example if it doesn't exist
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Edit /opt/findme/.env with your production values"
fi

# Bring up infrastructure and wait for services to be ready
docker compose up -d redis postgres
echo "Waiting for DB and Redis..."
# Simple check loop for health
until docker compose exec -T postgres pg_isready -U barakganon -d buyme_search; do
  sleep 2
done

# Run migrations
docker compose run --rm api python -m alembic upgrade head

# Start full stack
docker compose up -d api celery-worker celery-beat

# Configure nginx
sudo cp deployment/nginx.conf /etc/nginx/sites-available/findme
sudo ln -sf /etc/nginx/sites-available/findme /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

echo "Setup complete."
echo "  1. Edit /opt/findme/.env with production values"
echo "  2. Run: sudo certbot --nginx -d yourdomain.co.il"
