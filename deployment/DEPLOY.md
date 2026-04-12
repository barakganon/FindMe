# FindMe — Deployment Guide

## Architecture
- **Frontend**: React SPA → AWS S3 + CloudFront (CDN)
- **Backend**: FastAPI → EC2 (Docker) behind nginx
- **DB**: PostgreSQL + pgvector on EC2 (or RDS for production)
- **Cache**: Redis on EC2 (or ElastiCache for production)
- **CI/CD**: GitHub Actions

## GitHub Actions Secrets Required

| Secret | Description |
|--------|-------------|
| `GEMINI_API_KEY` | Google Gemini API key |
| `JWT_SECRET` | Random 64-char string for JWT signing |
| `DOCKERHUB_USERNAME` | Docker Hub username |
| `DOCKERHUB_TOKEN` | Docker Hub access token |
| `AWS_ACCESS_KEY_ID` | AWS IAM key with S3+CloudFront permissions |
| `AWS_SECRET_ACCESS_KEY` | AWS IAM secret |
| `AWS_REGION` | e.g. `eu-west-1` |
| `S3_BUCKET_NAME` | S3 bucket name for frontend |
| `CLOUDFRONT_DISTRIBUTION_ID` | CloudFront distribution ID |
| `EC2_HOST` | EC2 public IP or domain |
| `EC2_USER` | EC2 SSH user (usually `ubuntu`) |
| `EC2_SSH_KEY` | EC2 private key (full PEM content) |
| `VITE_API_URL` | Backend URL, e.g. `https://api.findme.co.il` |

## First Deployment

1. Launch EC2 instance (Ubuntu 22.04, t3.medium or larger)
2. Open ports 80, 443, 22 in security group
3. SSH in and run: `bash deployment/setup-ec2.sh`
4. Edit `/opt/findme/.env` with production values
5. Add GitHub Actions secrets (table above)
6. Push to master → CI runs → Docker image built → EC2 + S3 deployed

## Frontend-Only Deploy (S3)

```bash
cd frontend
VITE_API_URL=https://your-api-domain.com npm run build
aws s3 sync dist/ s3://your-bucket/ --delete
aws cloudfront create-invalidation --distribution-id XXXXX --paths "/*"
```

## Monitoring Strategy

To ensure high availability and performance of the FindMe application, we implement multi-layer monitoring:

### 1. Application-Level Monitoring
We expose health check endpoints in the backend to provide visibility into component health and performance:
- `/api/admin/health`: Provides system-level status, including database and Redis connectivity, operational latency (ms), and recent scrape task status.
- `/api/admin/health/detailed`: Offers detailed system diagnostics, including environment configuration, python version, and platform info.

### 2. External Monitoring (Availability)
Use **UptimeRobot** (or similar tools) to perform external probes every 5 minutes:
- **Ping `/health`**: Checks if the API is reachable.
- **Probe `/api/admin/health`**: Validates that critical backend services (Database, Redis) are responsive and latency is within acceptable limits.

### 3. Log Aggregation & Metrics (CloudWatch)
For production deployments on AWS, configure the following CloudWatch monitors:
- **CloudWatch Logs**: Centralize logs from Docker containers for troubleshooting application errors.
- **CloudWatch Metrics**: 
    - Monitor CPU and memory utilization on EC2 instances.
    - Set up CloudWatch Alarms for the `/api/admin/health` endpoint to trigger notifications if `latency_ms` exceeds defined thresholds (e.g., > 200ms).
    - Track 5xx error rates to detect service degradations early.
