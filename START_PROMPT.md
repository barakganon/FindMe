# Production Deploy Sprint — START_PROMPT

> **Goal:** ship FindMe to a public URL this weekend. Use the existing Docker, nginx, and
> GitHub Actions infrastructure that's already in the repo. Do NOT rewrite any of it.

---

## Cost estimate (monthly, v1 traffic)

| Item | Cost |
|------|------|
| EC2 `t3.medium` (2 vCPU, 4GB) + 30GB EBS | ~$35 |
| S3 + CloudFront (low traffic) | ~$2 |
| Route53 hosted zone | $0.50 |
| `.co.il` domain (yearly) | ~$15–25 |
| Gemini paid tier (chat + embedding) | ~$10–30 |
| Google Maps Geocoding (one-time, 500 stores) | ~$2.50 |
| **Total** | **~$50/mo** |

**Cheaper alternative — if you'd rather spend $10/mo for v1:**
Skip AWS. Deploy backend to **Render** ($7/mo for Starter), frontend to **Vercel** (free tier),
DB to **Supabase free tier** or Render postgres ($7/mo). Total ~$10–15/mo. The Dockerfile in
the repo runs unchanged on Render. Trade-off: you give up the existing GitHub Actions workflows.
**Recommendation: stick with AWS** for v1 because the tooling is already wired. You can always
migrate later if costs become a problem.
</br>

---

## PRE-FLIGHT — human steps (do these BEFORE pasting the prompt below)

These cannot be automated. Allocate ~60–90 minutes.

1. **AWS account** — create at https://aws.amazon.com if you don't have one. Add a payment method.
2. **IAM user for deploy** — create an IAM user with these AWS-managed policies:
   - `AmazonS3FullAccess`
   - `CloudFrontFullAccess`
   - `AmazonEC2FullAccess`
   - `AmazonRoute53FullAccess`
   Generate access keys for this user. Save them somewhere safe.
3. **Domain** — register `findme.co.il` (or alternative) at any .il registrar (e.g., domain.co.il, Domain The Net, Hostinger). About 60–90 ILS/year.
4. **Install AWS CLI + GitHub CLI locally:**
   ```bash
   brew install awscli gh
   aws configure          # paste IAM access keys
   gh auth login          # authenticate to GitHub
   ```
5. **Verify everything works:**
   ```bash
   aws sts get-caller-identity   # should print your IAM user ARN
   gh repo view barakganon/FindMe   # should show repo info
   ```

When all 5 are done, paste the prompt below into Claude Code in the FindMe directory.

---

## ─────────────────────────────────────────────────────────────────
## PASTE EVERYTHING BELOW THIS LINE INTO CLAUDE CODE
## ─────────────────────────────────────────────────────────────────

Read these files fully before doing anything:
- `CLAUDE.md`
- `STATUS.md`
- `deployment/DEPLOY.md`
- `deployment/setup-ec2.sh`
- `deployment/nginx.conf`
- `.github/workflows/ci.yml`
- `.github/workflows/deploy-backend.yml`
- `.github/workflows/deploy-frontend.yml`
- `Dockerfile`
- `docker-compose.yml`
- `docker-compose.override.yml`
- `.env.example`

You are the **Deploy Agent**. Execute this sprint in 6 sequential phases. Each phase
has an explicit checkpoint — confirm it passes before proceeding. Never skip a phase.
If a phase fails, **stop immediately**, report the failure, and ask the human for guidance.

The user expects you to be persistent and complete the deploy autonomously where possible,
asking only when AWS console action is genuinely required.

---

### GIT SETUP (do this once before Phase 1)

```bash
cd /Users/barakganon/PycharmProjects/PythonProject/FindMe
git checkout master && git pull origin master
git checkout -b infra/aws-production-deploy
```

All file changes in this sprint go on this branch. Commit per phase with conventional commits.

---

### PHASE 1 — gather deployment values from the human

Ask the human (in chat) for these values, one prompt with all of them at once:

```
Before I can configure anything, I need these values from you:

  1. AWS account ID (12-digit number) — find at https://console.aws.amazon.com → top-right
  2. AWS region (suggest "eu-west-1" — Ireland, closest fast AWS region to Israel)
  3. Domain you registered (e.g., "findme.co.il")
  4. The IAM access key ID and secret you created (paste here only — I'll write to .env locally, never commit)
  5. Whether you want to use RDS for postgres ($15/mo extra, more reliable) OR docker postgres on EC2 (free, fine for v1)

Reply with all 5 values in one message and I'll proceed.
```

WAIT for the human's reply. Do not proceed without all 5 values.

---

### PHASE 2 — generate production secrets and prepare files

Now you have the values. Do these tasks:

**Task 2.1 — generate strong JWT secret**
```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```
Save the output — you'll inject it into the EC2 `.env` later.

**Task 2.2 — populate production `.env.production` (NOT committed)**

Create `/Users/barakganon/PycharmProjects/PythonProject/FindMe/.env.production` (it's already in `.gitignore` via `.env*`). Use the human's values + the JWT secret you just generated. Use this template — fill in all `<...>` placeholders:

```
DATABASE_URL=postgresql+asyncpg://findme:<generate-strong-pw>@postgres:5432/buyme_search
DATABASE_URL_SYNC=postgresql+psycopg2://findme:<same-pw>@postgres:5432/buyme_search
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
GEMINI_API_KEY=<copy from current .env>
GOOGLE_MAPS_API_KEY=<leave blank — Phase 5 task>
JWT_SECRET=<paste from Task 2.1>
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO
CORS_ORIGINS=https://<domain>,https://www.<domain>
SEARCH_CACHE_TTL=300
INTENT_CACHE_TTL=120
EMBED_BATCH_SIZE=100
SHOPIFY_SCRAPE_CONCURRENCY=5
```

Confirm `.env.production` is gitignored: `git status` must show it as untracked-but-ignored. If it shows as a new file to commit, **STOP** and check `.gitignore`.

**Task 2.3 — verify the existing infrastructure is sound (read-only)**
```bash
# These should all exist already. If any is missing, STOP and report.
ls -la Dockerfile docker-compose.yml docker-compose.override.yml deployment/setup-ec2.sh deployment/nginx.conf
ls -la .github/workflows/ci.yml .github/workflows/deploy-backend.yml .github/workflows/deploy-frontend.yml
```

**Task 2.4 — update nginx.conf with the actual domain if it's not findme.co.il**

If the human's domain is different from `findme.co.il`, edit `deployment/nginx.conf` and replace all 4 occurrences of `findme.co.il` (and `www.findme.co.il`) with the actual domain.

```bash
git add deployment/nginx.conf
git commit -m "chore(deploy): update nginx.conf with production domain"
```

If the domain IS `findme.co.il`, skip this commit.

**Checkpoint 2:** `.env.production` exists locally and is gitignored. nginx.conf has the right domain.

---

### PHASE 3 — provision AWS infrastructure

**Task 3.1 — create S3 bucket for frontend**

```bash
DOMAIN="<the domain from Phase 1>"
REGION="<the region from Phase 1>"
BUCKET_NAME="$DOMAIN-frontend"   # e.g. findme.co.il-frontend

aws s3 mb s3://$BUCKET_NAME --region $REGION
aws s3api put-bucket-versioning --bucket $BUCKET_NAME --versioning-configuration Status=Enabled
```

Save the bucket name — you'll need it for GitHub secrets.

**Task 3.2 — launch EC2 instance**

This step is best done in the AWS console because the IAM user needs to attach a key pair, and key creation in CLI is awkward.

Tell the human:
```
Open AWS Console → EC2 → Launch Instance:
  - Name: findme-prod
  - AMI: Ubuntu Server 22.04 LTS (free tier eligible)
  - Instance type: t3.medium
  - Key pair: create a new one named "findme-deploy-key", DOWNLOAD THE .pem FILE — save it to ~/.ssh/findme-deploy-key.pem
  - Security group: create new, allow:
      • SSH (22) from your IP only
      • HTTP (80) from anywhere
      • HTTPS (443) from anywhere
  - Storage: 30 GB gp3
  - Launch.

Once launched, give me the public IPv4 address.
```

WAIT for the human's reply with the EC2 public IP. Save it as `EC2_HOST`.

Set permissions on the key:
```bash
chmod 600 ~/.ssh/findme-deploy-key.pem
```

**Task 3.3 — create CloudFront distribution**

Tell the human:
```
Open AWS Console → CloudFront → Create distribution:
  - Origin domain: select <BUCKET_NAME>.s3.<region>.amazonaws.com from dropdown
  - Origin access: "Origin access control" → Create new OAC for this origin
  - Viewer protocol policy: Redirect HTTP to HTTPS
  - Allowed HTTP methods: GET, HEAD, OPTIONS
  - Cache policy: CachingOptimized
  - Default root object: index.html
  - Custom error responses → Create:
      • 403 → /index.html, response code 200, TTL 0  (SPA routing)
      • 404 → /index.html, response code 200, TTL 0
  - Alternate domain (CNAME): your domain (e.g. findme.co.il, www.findme.co.il)
  - SSL certificate: "Request certificate in ACM" — request one in us-east-1 for the domain
       (CloudFront ONLY accepts certs from us-east-1, regardless of your main region)
  - Create distribution.

Once it's deployed (~5 min), give me the Distribution ID and the *.cloudfront.net domain it assigned.

After creation, click the distribution → Origins tab → Copy the bucket policy CloudFront generated and paste it on the S3 bucket (Permissions → Bucket policy).
```

WAIT for: distribution ID + .cloudfront.net domain.

**Task 3.4 — create Route53 hosted zone + DNS records**

```bash
DOMAIN="<the domain>"
aws route53 create-hosted-zone --name $DOMAIN --caller-reference "findme-deploy-$(date +%s)"
```

Note the 4 NS records returned. Tell the human:
```
Go to your domain registrar's control panel and update the nameservers to these 4 AWS nameservers:
[paste the NS records from above]

This propagates in 5min–48hr. Tell me when you've updated them.
```

WAIT for confirmation.

Once the human confirms, create DNS records:
```bash
ZONE_ID=$(aws route53 list-hosted-zones-by-name --dns-name $DOMAIN --query 'HostedZones[0].Id' --output text | sed 's|/hostedzone/||')

# A record for api.<domain> → EC2 (use Route53 Alias would be nicer but A is fine for now)
aws route53 change-resource-record-sets --hosted-zone-id $ZONE_ID --change-batch '{
  "Changes":[{"Action":"UPSERT","ResourceRecordSet":{
    "Name":"api.'$DOMAIN'","Type":"A","TTL":300,
    "ResourceRecords":[{"Value":"<EC2_HOST>"}]
  }}]
}'

# CNAME for www → root
aws route53 change-resource-record-sets --hosted-zone-id $ZONE_ID --change-batch '{
  "Changes":[{"Action":"UPSERT","ResourceRecordSet":{
    "Name":"www.'$DOMAIN'","Type":"CNAME","TTL":300,
    "ResourceRecords":[{"Value":"'$DOMAIN'"}]
  }}]
}'

# Root → CloudFront alias (only via Route53 Alias, not CNAME)
aws route53 change-resource-record-sets --hosted-zone-id $ZONE_ID --change-batch '{
  "Changes":[{"Action":"UPSERT","ResourceRecordSet":{
    "Name":"'$DOMAIN'","Type":"A","AliasTarget":{
      "HostedZoneId":"Z2FDTNDATAQYW2",
      "DNSName":"<the cloudfront domain>",
      "EvaluateTargetHealth":false
    }
  }}]
}'
```

**Checkpoint 3:** S3 bucket exists, EC2 running, CloudFront deployed, Route53 zone with 3 records. `dig $DOMAIN` should resolve to CloudFront within 5–60 minutes (DNS propagation).

```bash
git commit --allow-empty -m "infra(aws): provision S3, EC2, CloudFront, Route53 (manual via console + CLI)"
```

---

### PHASE 4 — set up EC2 + first backend deploy

**Task 4.1 — SSH in and run setup script**

```bash
ssh -i ~/.ssh/findme-deploy-key.pem ubuntu@<EC2_HOST>
# Once in:
git clone https://github.com/barakganon/FindMe.git /tmp/findme-clone
sudo bash /tmp/findme-clone/deployment/setup-ec2.sh
```

The script clones to `/opt/findme`, installs Docker, brings up redis+postgres, runs migrations, and starts the stack. **It will pause** if there are missing env vars.

**Task 4.2 — copy production .env to EC2**

In a separate terminal on your local machine:
```bash
scp -i ~/.ssh/findme-deploy-key.pem .env.production ubuntu@<EC2_HOST>:/tmp/.env
ssh -i ~/.ssh/findme-deploy-key.pem ubuntu@<EC2_HOST> "sudo mv /tmp/.env /opt/findme/.env && sudo chown ubuntu:ubuntu /opt/findme/.env && sudo chmod 600 /opt/findme/.env"
```

Then re-run the setup script's docker stage:
```bash
ssh -i ~/.ssh/findme-deploy-key.pem ubuntu@<EC2_HOST>
cd /opt/findme
docker compose up -d redis postgres
docker compose run --rm api python -m alembic upgrade head
docker compose up -d api celery-worker celery-beat
docker compose ps   # all should show "running" or "healthy"
curl http://localhost:8000/health   # should return {"status":"ok"}
```

**Task 4.3 — request SSL cert via certbot**

Still on EC2:
```bash
sudo certbot --nginx -d api.<domain>   # backend
# Choose: redirect HTTP → HTTPS when prompted
```

For the root + www domain (frontend), SSL is handled by CloudFront's ACM cert from Phase 3.

**Task 4.4 — test backend from outside**

From your local machine:
```bash
curl https://api.<domain>/health   # {"status":"ok"}
curl https://api.<domain>/api/admin/health   # JSON with DB + Redis status
```

If both work, the backend is live.

**Checkpoint 4:** `https://api.<domain>/health` returns 200 OK over HTTPS.

```bash
git commit --allow-empty -m "infra(deploy): EC2 setup complete, backend live at api.<domain>"
```

---

### PHASE 5 — wire GitHub Actions for continuous deploy

**Task 5.1 — set GitHub Actions secrets via gh CLI**

```bash
cd /Users/barakganon/PycharmProjects/PythonProject/FindMe

# Read these from the human's earlier reply or prompt for missing ones
gh secret set GEMINI_API_KEY --body "<value>"
gh secret set JWT_SECRET --body "<value from Task 2.1>"
gh secret set DOCKERHUB_USERNAME --body "<ask human>"
gh secret set DOCKERHUB_TOKEN --body "<ask human, generate at hub.docker.com/settings/security>"
gh secret set AWS_ACCESS_KEY_ID --body "<value>"
gh secret set AWS_SECRET_ACCESS_KEY --body "<value>"
gh secret set AWS_REGION --body "<region>"
gh secret set S3_BUCKET_NAME --body "<bucket name from Phase 3.1>"
gh secret set CLOUDFRONT_DISTRIBUTION_ID --body "<from Phase 3.3>"
gh secret set EC2_HOST --body "<EC2 public IP>"
gh secret set EC2_USER --body "ubuntu"
gh secret set EC2_SSH_KEY < ~/.ssh/findme-deploy-key.pem
gh secret set VITE_API_URL --body "https://api.<domain>"
```

If the human doesn't have a Docker Hub account, prompt them:
```
Need a Docker Hub account for the deploy-backend workflow. Create one free at hub.docker.com,
then go to Account Settings → Security → New Access Token, name it "findme-ci", read+write+delete scope.
Give me the username and token.
```

**Task 5.2 — verify all secrets set**
```bash
gh secret list
```
Should show 13 secrets. If any missing, set them.

**Task 5.3 — push the branch and trigger CI**

```bash
git push origin infra/aws-production-deploy
gh pr create --title "Production deploy: AWS infra + GitHub Actions secrets" --body "First production deployment. EC2 backend at api.<domain>, frontend at S3+CloudFront at <domain>."
```

Watch CI:
```bash
gh run watch
```

When CI passes, the deploy-backend and deploy-frontend workflows trigger automatically (they run on `workflow_run` of CI).

**Task 5.4 — merge to master**
After CI passes:
```bash
gh pr merge --merge   # use --merge (no-ff equivalent for GH PRs)
```

This triggers another CI run on master, which kicks off the actual prod deploy.

**Task 5.5 — verify deploy completed**

Watch the deploy workflows:
```bash
gh run watch                           # latest run
# Once finished, verify:
curl https://api.<domain>/api/admin/health
# Visit https://<domain> in a browser — should show the chat UI
```

**Checkpoint 5:** browser at `https://<domain>` shows the FindMe chat. Sending "אוזניות סוני" returns Hebrew results. `https://api.<domain>/api/admin/health` returns 99.3% embedding coverage.

---

### PHASE 6 — verification + parallel productivity

While Phase 4 and 5 wait on AWS provisioning, DNS propagation, etc., do these in parallel.
They don't block the deploy — they make the deployed product better.

**Task 6.1 — Google Maps geocoding for 500 stores**

Tell the human:
```
While we wait for DNS, let's geocode the 500 ungeocoded physical stores.
1. Go to https://console.cloud.google.com → APIs & Services → Library
2. Enable: "Geocoding API"
3. Credentials → Create credentials → API key
4. Restrict it to "Geocoding API" only (security)
5. Give me the key.
```

When you have the key:
```bash
# Add to LOCAL .env (for running the script locally)
echo "GOOGLE_MAPS_API_KEY=<key>" >> .env

# Also add to EC2 .env via ssh
ssh -i ~/.ssh/findme-deploy-key.pem ubuntu@<EC2_HOST> "echo 'GOOGLE_MAPS_API_KEY=<key>' | sudo tee -a /opt/findme/.env"

# Run geocoding locally (faster — DB is local)
source .venv/bin/activate
python -m db.run_geocoding
```

Cost: ~$2.50 for 500 stores at $0.005/request. Done in <10 minutes.

After it finishes, sync the geocoded data to EC2 OR re-run on EC2 — whichever is simpler. Easiest: dump and restore postgres.

Commit (the script wasn't changed but data was, so no commit needed unless config changed).

**Task 6.2 — run bulk deduplication**

```bash
source .venv/bin/activate
python -m normalization.deduplication --threshold 0.95 --apply
```

This will merge near-duplicate products across stores. The initial run found 10 merges at 0.99 threshold; lowering to 0.95 will catch more. Review the count before applying — if it's wildly higher than expected, raise the threshold.

**Task 6.3 — set up free uptime monitoring**

Tell the human:
```
Sign up free at https://uptimerobot.com (50 monitors free).
Add 2 HTTP monitors:
  1. https://api.<domain>/health — every 5 min
  2. https://<domain> — every 5 min
Both should email/SMS you on failure.
```

**Task 6.4 — final smoke test**

From your local machine:
```bash
# Backend health
curl -s https://api.<domain>/api/admin/health | jq

# Anonymous chat
curl -s -X POST https://api.<domain>/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"אוזניות סוני","history":[],"session_context":null}' | jq .message

# Register a real test user
curl -s -X POST https://api.<domain>/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"barakganon+test@gmail.com","password":"<strong-pw>","display_name":"Barak"}' | jq

# Frontend
open https://<domain>     # macOS opens in browser
```

**Checkpoint 6:** all 4 smoke tests pass. The deploy is done.

---

### PHASE 7 — ship the announcement

You don't need Claude Code for this part. Tell some real humans the URL. Suggested first audiences:

1. Your wife (test from her phone)
2. WhatsApp groups for your kids' school parents (Israeli, Hebrew users, gift-card-owners)
3. Israeli developer subreddits or Facebook groups (r/Israel, "ישראלים בהייטק")
4. Friends who hold BuyMe cards

Track what people search for via the `user_search_history` table:
```bash
ssh -i ~/.ssh/findme-deploy-key.pem ubuntu@<EC2_HOST> \
  "docker compose exec postgres psql -U findme -d buyme_search -c 'SELECT message, intent, result_count FROM user_search_history ORDER BY searched_at DESC LIMIT 50;'"
```

This is the data that tells you whether to add Tav HaZahav next, fix specific search bugs, or pivot.

---

### Final orchestrator step — merge + update docs

Once Checkpoint 6 passes:

```bash
git checkout master
git pull origin master
# (PR was already merged in Phase 5.4 — this just syncs)

# Update CLAUDE.md current state section: add "✅ Production Deployment — live at https://<domain>"
# Update STATUS.md with a "## Production Deployed" section listing the URLs and the date

git add CLAUDE.md STATUS.md
git commit -m "docs: production deploy complete, live at https://<domain>"
git push origin master
```

---

### ROLLBACK (if anything breaks badly)

If the production site is broken and you need to revert immediately:

```bash
# SSH to EC2
ssh -i ~/.ssh/findme-deploy-key.pem ubuntu@<EC2_HOST>
cd /opt/findme
git log --oneline -5            # find the previous good commit
git checkout <previous-good-sha>
docker compose pull
docker compose up -d --no-deps api
```

For the frontend, use the S3 versioning enabled in Phase 3.1 to restore a prior `index.html` version.

---

## HARD RULES FOR THIS SPRINT

- Never commit `.env.production`, `.env`, or any AWS keys to git
- Never paste IAM credentials into a shell history that's saved — use `aws configure` once and never again
- Never SSH into EC2 with a wide-open security group (22 from anywhere) — restrict to your IP
- If a phase checkpoint fails, **STOP and report** — do not "try the next thing"
- Branch pushed AND CI green AND smoke tests pass = task done. Anything less = not done.
- After the sprint, delete the local `infra/aws-production-deploy` branch: `git branch -d infra/aws-production-deploy`

## ─────────────────────────────────────────────────────────────────
## END — copy everything above into Claude Code
## ─────────────────────────────────────────────────────────────────
