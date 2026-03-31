---
name: deploy-cloudrun
description: Deploy the MiroFish Trading backend to Google Cloud Run
---

# Deploy to Google Cloud Run

## Prerequisites

1. **gcloud CLI**: `brew install --cask google-cloud-sdk`
2. **Authentication**: `gcloud auth login`
3. **Project**: `gcloud config set project total-now-339022`
4. **APIs enabled**: Cloud Run, Cloud Build, Artifact Registry, Secret Manager

## Quick Deploy

```bash
bash scripts/deploy_cloudrun.sh
```

The script will prompt for secrets (API keys) if they don't already exist in Secret Manager.

## Configuration

Override defaults via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `GCP_PROJECT_ID` | `total-now-339022` | GCP project ID |
| `GCP_REGION` | `us-west2` | Cloud Run region |
| `SERVICE_NAME` | `mirofish-trading` | Cloud Run service name |
| `GCS_BUCKET` | `{PROJECT_ID}-mirofish-results` | GCS bucket for simulation persistence (auto-created) |

## Secrets

Managed via Google Secret Manager:

| Secret | Required | Description |
|--------|----------|-------------|
| `LLM_API_KEY` | Yes | OpenAI API key for primary LLM (institutional agents) |
| `LLM_BOOST_API_KEY` | Yes | OpenAI API key for boost LLM (retail agents) |
| `ZEP_API_KEY` | No | Zep Cloud API key for knowledge graph memory |

### Updating secrets

```bash
echo -n "sk-new-key" | gcloud secrets versions add LLM_API_KEY --data-file=-
# Then redeploy or restart:
gcloud run services update mirofish-trading --region us-west2
```

## Verification

```bash
SERVICE_URL=$(gcloud run services describe mirofish-trading --region us-west2 --format 'value(status.url)')

# Health check
curl -s "${SERVICE_URL}/api/health" | python3 -m json.tool

# Run simulation
curl -s -X POST "${SERVICE_URL}/api/simulations" \
  -H "Content-Type: application/json" \
  -d '{"scenario": "scenario_a", "seed": 42, "agents": {"institutional": 3, "retail": 5, "market_maker": 1, "noise": 5}}' \
  | python3 -m json.tool
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `PERMISSION_DENIED` on secrets | Re-run deploy script — it grants access to the compute SA |
| Timeout on simulation | Increase `--timeout` in deploy script (default 300s) |
| Cold start slow | Set `MIN_INSTANCES=1` to keep one instance warm (costs ~$10/mo) |
| OOM errors | Increase `MEMORY` to `2Gi` in deploy script |

## Logs

```bash
gcloud run services logs read mirofish-trading --region us-west2 --limit 50
```
