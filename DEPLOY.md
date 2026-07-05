# Deploy — Railway (backend) + Netlify (frontend) + Supabase (database)

Run every command on your Mac from the project root:
`cd "/Users/kaplan/Claude/Projects/AI DENTAL CAD GEN"`

## 0. Install the CLIs (once)

```bash
npm install -g netlify-cli @railway/cli supabase
```

## 1. Supabase — database

```bash
supabase login                            # opens browser
supabase projects create aidcad --region eu-central-1
supabase link --project-ref <ref-from-output>
supabase db push                          # applies supabase/migrations/0001_init.sql
```

Get the connection string (this is what the backend uses):

```bash
# Dashboard → Project Settings → Database → Connection string → URI
# Use the "Transaction pooler" URI and replace [YOUR-PASSWORD]:
# postgresql://postgres.<ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres
```

## 2. Railway — backend

```bash
cd backend
railway login                             # opens browser
railway init                              # create new project, name it aidcad-api
railway up                                # first deploy (builds from requirements.txt + railway.toml)
railway domain                            # generates https://<app>.up.railway.app — note it
```

Set environment variables:

```bash
railway variables --set "ANTHROPIC_API_KEY=sk-ant-..." \
                  --set "DATABASE_URL=postgresql://postgres.<ref>:<pw>@...pooler.supabase.com:6543/postgres" \
                  --set "AIDCAD_DATA_DIR=/data" \
                  --set "AIDCAD_CORS=https://<your-site>.netlify.app,http://localhost:3000"
railway volume add --mount-path /data     # persistent disk for scans/renders/packages
railway up                                # redeploy with vars
```

Test: open `https://<app>.up.railway.app/health` → `{"status":"ok"}`.

Notes:
- For testing without burning API credit, set `AIDCAD_MOCK=1` instead of the API key.
- For much better renders (better perception), uncomment `open3d` in `backend/requirements.txt` and redeploy — needs the £20 plan's memory.

## 3. Netlify — frontend

```bash
cd ../frontend
npm install
netlify login                             # opens browser
netlify init                              # create & configure new site
netlify env:set NEXT_PUBLIC_API_URL https://<app>.up.railway.app
netlify deploy --build --prod
```

Then update the backend CORS if your Netlify URL changed:

```bash
cd ../backend
railway variables --set "AIDCAD_CORS=https://<your-site>.netlify.app,http://localhost:3000"
railway up
```

## 4. Verify end-to-end

1. Open the Netlify URL → upload `üst öncesi 1.stl` → Analyse.
2. Watch backend logs live: `cd backend && railway logs`.
3. Case rows appear in Supabase: Dashboard → Table Editor → `cases` / `audit`.

## Redeploying after changes

```bash
cd backend && railway up                  # backend
cd frontend && netlify deploy --build --prod   # frontend
```

## Local dev (unchanged)

```bash
cd backend && AIDCAD_MOCK=1 uvicorn app.main:app --port 8000
cd frontend && npm run dev
```

Without `DATABASE_URL` the backend falls back to local SQLite automatically.
