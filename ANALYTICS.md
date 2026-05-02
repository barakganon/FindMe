# FindMe — First-Week Analytics Playbook

> What to query in the first 7 days after launch to know if FindMe is working.
> All queries run against the production Postgres on EC2 (or Render).

---

## How to run

```bash
# AWS path
ssh -i ~/.ssh/findme-deploy-key.pem ubuntu@<EC2_HOST>
cd /opt/findme
docker compose exec postgres psql -U findme -d buyme_search

# Or one-shot from local machine:
ssh -i ~/.ssh/findme-deploy-key.pem ubuntu@<EC2_HOST> \
  "docker compose -f /opt/findme/docker-compose.yml exec -T postgres \
   psql -U findme -d buyme_search -c \"$QUERY\""

# Render path
# Use the Render dashboard's Postgres "External Database URL" and connect with psql locally:
psql <render-external-database-url>
```

For convenience, save the queries below as `analytics.sql` and run:
```bash
docker compose exec -T postgres psql -U findme -d buyme_search < analytics.sql
```

---

## Tier 1 — am I getting traffic at all? (run daily)

### How many searches in the last 24h, 7d, all-time

```sql
SELECT
  count(*) FILTER (WHERE searched_at > now() - interval '24 hours') AS last_24h,
  count(*) FILTER (WHERE searched_at > now() - interval '7 days')   AS last_7d,
  count(*)                                                          AS all_time
FROM user_search_history;
```

**What it tells you:** rough usage. If `last_24h = 0` for two days in a row after telling people about it, distribution is the problem, not the product.

### Distinct users in the last 24h, 7d

```sql
SELECT
  count(DISTINCT user_id) FILTER (WHERE searched_at > now() - interval '24 hours') AS dau,
  count(DISTINCT user_id) FILTER (WHERE searched_at > now() - interval '7 days')   AS wau
FROM user_search_history;
```

**Note:** this only counts *registered* users. Anonymous traffic is not in `user_search_history`. For full traffic, see the nginx access log or add a hit counter (Tier 4).

---

## Tier 2 — what are people actually searching for? (run every 2-3 days)

### Top 30 search messages this week

```sql
SELECT
  message,
  count(*) AS times_asked,
  avg(result_count)::int AS avg_results,
  count(*) FILTER (WHERE result_count = 0) AS zero_result_count
FROM user_search_history
WHERE searched_at > now() - interval '7 days'
GROUP BY message
ORDER BY times_asked DESC
LIMIT 30;
```

**What it tells you:**
- Real Hebrew that real users type (gold for prompt tuning)
- Patterns you can systemize: if 5 people typed "אוזניות bluetooth", that's a category to surface in suggestion chips
- Spelling/typo variations the intent parser needs to handle

### Intent breakdown — how often does the LLM understand vs ask for clarification

```sql
SELECT
  intent,
  count(*) AS hits,
  round(avg(result_count)::numeric, 1) AS avg_results,
  count(*) FILTER (WHERE result_count = 0) AS zero_result_hits
FROM user_search_history
WHERE searched_at > now() - interval '7 days'
GROUP BY intent
ORDER BY hits DESC;
```

**Healthy distribution:**
- `product_search` ~50–70%
- `store_search` ~15–25%
- `help` ~5–15% (first-time visitors)
- `clarify` <10% (more than 10% = intent parser is too strict)

If `clarify` is dominant, the intent parser is failing — review the failing messages and tighten the Hebrew prompt.

### Zero-result queries (what we're failing on)

```sql
SELECT message, intent, count(*) AS times
FROM user_search_history
WHERE result_count = 0
  AND searched_at > now() - interval '7 days'
GROUP BY message, intent
ORDER BY times DESC
LIMIT 20;
```

**What it tells you:** the gap between user expectations and FindMe's catalog. If "מקלדת מכנית" returns zero results, there's no mechanical-keyboard product in the catalog — meaning either CrypTech wasn't scraped recently or the embedding for that term is weak. Both fixable.

---

## Tier 3 — are people coming back? (run weekly)

### Returning users (registered)

```sql
SELECT count(*)
FROM (
  SELECT user_id
  FROM user_search_history
  WHERE searched_at > now() - interval '7 days'
  GROUP BY user_id
  HAVING count(DISTINCT date(searched_at)) >= 2
) AS returning;
```

**What it tells you:** users who came back on a different day. The single most predictive metric for "this is real."

### Sessions per user

```sql
SELECT
  count(*) FILTER (WHERE searches = 1)              AS one_search_users,
  count(*) FILTER (WHERE searches BETWEEN 2 AND 5)  AS light_users,
  count(*) FILTER (WHERE searches BETWEEN 6 AND 20) AS regular_users,
  count(*) FILTER (WHERE searches > 20)             AS heavy_users
FROM (
  SELECT user_id, count(*) AS searches
  FROM user_search_history
  WHERE searched_at > now() - interval '7 days'
  GROUP BY user_id
) per_user;
```

**Healthy distribution:** roughly even split between one-search and light. Heavy users suggest you've found a real use case worth investing in.

### Anonymous → registered conversion

```sql
-- Total registrations in the period
SELECT count(*) AS new_users_7d
FROM users
WHERE created_at > now() - interval '7 days';

-- Imported sessions vs from-scratch registrations
SELECT
  count(*) FILTER (WHERE EXISTS (
    SELECT 1 FROM user_search_history h
    WHERE h.user_id = u.id
      AND h.searched_at < u.created_at + interval '5 minutes'
  )) AS imported_their_session,
  count(*) AS total
FROM users u
WHERE created_at > now() - interval '7 days';
```

**What it tells you:** the "soft prompt after 3rd search" flow is working if `imported_their_session / total` is high. If near zero, either nobody is registering, or the import-session flow is broken.

---

## Tier 4 — anonymous traffic (NOT in user_search_history)

Anonymous users don't write to `user_search_history`. Two options:

**Option A — nginx access log on EC2:**
```bash
ssh ubuntu@<EC2_HOST> "sudo grep '/api/chat' /var/log/nginx/access.log | wc -l"
ssh ubuntu@<EC2_HOST> "sudo awk '\$7==\"/api/chat\" {print}' /var/log/nginx/access.log | tail -50"
```

**Option B — add a `chat_request_log` table** (10-min DB migration, recommended for week 2):
```sql
CREATE TABLE chat_request_log (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid REFERENCES users(id) ON DELETE SET NULL,
  is_anonymous boolean NOT NULL,
  message_hash char(64) NOT NULL,
  intent      varchar(50),
  result_count int,
  has_gps     boolean,
  city_used   varchar(100),
  searched_at timestamptz DEFAULT now()
);
CREATE INDEX idx_chat_log_searched_at ON chat_request_log(searched_at DESC);
```

The hash lets you count usage without storing anonymous user messages (privacy-preserving).
Wire it into `api/routes/chat.py` after the response is built — never block the user.

---

## Tier 5 — voucher network signal (run weekly)

### Most-clicked store types (from results)

```sql
SELECT
  s.buyme_category,
  count(DISTINCT h.user_id) AS unique_searchers,
  count(*) AS appearances_in_results
FROM user_search_history h
JOIN stores s ON s.name_he = h.top_result_name OR s.name_en = h.top_result_name
WHERE h.searched_at > now() - interval '7 days'
GROUP BY s.buyme_category
ORDER BY appearances_in_results DESC;
```

**What it tells you:** which BuyMe categories pull weight. If 80% of top results are restaurants, FindMe's main value is "find restaurants near me that take BuyMe" — and that should drive the homepage suggestion chips.

### Cities people search in

```sql
SELECT city_used, count(*) AS searches, count(DISTINCT user_id) AS users
FROM user_search_history
WHERE city_used IS NOT NULL
  AND searched_at > now() - interval '7 days'
GROUP BY city_used
ORDER BY searches DESC
LIMIT 15;
```

**What it tells you:** geographic audience. If Tel Aviv + Bat Yam dominate, the 500 ungeocoded stores in those cities are the highest-leverage data fix. If Eilat shows up a lot, it's vacation-driven traffic.

---

## Decision rules (for week 2)

After 7 days of data, use these to decide what to do next:

| Signal | Decision |
|--------|----------|
| `last_7d searches < 20` | Distribution problem. Don't add features — get more eyes on it. Post in 2 more communities. |
| `clarify > 20% of intents` | Intent parser too strict. Review the top clarify messages, tighten `INTENT_PARSER_SYSTEM`. |
| `zero_result_count > 30%` | Catalog gap. Add to scrape queue or add Tav HaZahav now (more catalogs = fewer zero-result hits). |
| `returning_users > 5` | You have a real product. Time to add the voucher wallet (multi-card support). |
| `imported_session/total < 0.3` | Soft-registration prompt isn't converting. Test the prompt copy. Maybe move it earlier. |
| `anonymous traffic >> registered` | Value of registering isn't clear. Worth A/B testing the prompt timing. |
| Heavy user shows up | Reach out to them. One real heavy user is worth 1000 anonymous visitors for product feedback. |

---

## Quick "is it alive?" health check

Save this as `~/findme-status` on EC2 for daily runs:

```bash
#!/bin/bash
cd /opt/findme
echo "=== FindMe Status ==="
echo
echo "Health endpoint:"
curl -s https://api.<domain>/api/admin/health | jq '.products_total, .embedding_coverage_pct, .stores_total'
echo
echo "Last 24h searches (registered users only):"
docker compose exec -T postgres psql -U findme -d buyme_search -c \
  "SELECT count(*) AS searches, count(DISTINCT user_id) AS users
   FROM user_search_history WHERE searched_at > now() - interval '24 hours';"
echo
echo "Last 24h registrations:"
docker compose exec -T postgres psql -U findme -d buyme_search -c \
  "SELECT count(*) AS new_users
   FROM users WHERE created_at > now() - interval '24 hours';"
echo
echo "Top 5 messages last 24h:"
docker compose exec -T postgres psql -U findme -d buyme_search -c \
  "SELECT message, count(*) FROM user_search_history
   WHERE searched_at > now() - interval '24 hours'
   GROUP BY message ORDER BY count DESC LIMIT 5;"
```

Run with: `bash ~/findme-status`
