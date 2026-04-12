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

## Frontend Security (S3 & CloudFront)

To secure the frontend, implement the following:

### 1. S3 Bucket Policy
Restrict S3 access to only allow requests from the CloudFront Origin Access Control (OAC):

```json
{
  "Version": "2012-10-17",
  "Statement": {
    "Sid": "AllowCloudFrontServicePrincipalReadOnly",
    "Effect": "Allow",
    "Principal": {
      "Service": "cloudfront.amazonaws.com"
    },
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::YOUR_BUCKET_NAME/*",
    "Condition": {
      "StringEquals": {
        "AWS:SourceArn": "arn:aws:cloudfront::YOUR_ACCOUNT_ID:distribution/YOUR_DISTRIBUTION_ID"
      }
    }
  }
}
```

### 2. CloudFront Origin Access Control (OAC)
- Create an OAC in CloudFront.
- Update your S3 Origin to use this OAC.
- Ensure the S3 bucket is **not** public.

## Useful Commands

```bash
# On EC2
cd /opt/findme
docker compose logs api -f          # API logs
docker compose logs celery-worker   # Celery logs
docker compose exec api pytest tests/ -v  # Run tests
docker compose exec api python -m alembic upgrade head  # Migrations

# Check Redis
docker compose exec redis redis-cli ping

# Admin health
curl https://your-domain.com/api/admin/health
```
