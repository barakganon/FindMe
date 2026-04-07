#!/bin/bash
# Run once on a fresh Ubuntu 22.04 EC2 instance
set -e

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu

# Install nginx + certbot
sudo apt-get install -y nginx certbot python3-certbot-nginx

# Clone repo
sudo mkdir -p /opt/findme
sudo chown ubuntu:ubuntu /opt/findme
git clone https://github.com/barakganon/FindMe.git /opt/findme
cd /opt/findme

# Create .env from example
cp .env.example .env
echo "Edit /opt/findme/.env with your production values"

# Start services
docker compose up -d redis postgres
sleep 5
docker compose up -d api celery-worker celery-beat
docker compose exec api python -m alembic upgrade head

# Configure nginx
sudo cp deployment/nginx.conf /etc/nginx/sites-available/findme
sudo ln -sf /etc/nginx/sites-available/findme /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# SSL (replace with your domain)
# sudo certbot --nginx -d findme.co.il -d www.findme.co.il

echo "Setup complete. Remember to:"
echo "  1. Edit /opt/findme/.env with production values"
echo "  2. Run: sudo certbot --nginx -d yourdomain.co.il"
echo "  3. Add GitHub Actions secrets (see deployment/DEPLOY.md)"
