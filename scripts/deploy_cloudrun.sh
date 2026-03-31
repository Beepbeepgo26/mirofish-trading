#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# Deploy MiroFish Trading Simulation to Google Cloud Run
# ──────────────────────────────────────────────────────────
set -euo pipefail

# ─── Configuration ───
PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-us-west2}"
SERVICE_NAME="mirofish-trading"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  MiroFish Trading — Cloud Run Deployment            ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ─── Validate prerequisites ───
if [ -z "$PROJECT_ID" ]; then
    echo "❌ GCP_PROJECT_ID not set."
    echo "   Run: export GCP_PROJECT_ID=your-project-id"
    echo "   Or:  gcloud config get-value project"
    exit 1
fi

if ! command -v gcloud &> /dev/null; then
    echo "❌ gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

echo "  Project:  $PROJECT_ID"
echo "  Region:   $REGION"
echo "  Service:  $SERVICE_NAME"
echo ""

# ─── Step 1: Enable required APIs ───
echo "► Enabling Cloud Run and related APIs..."
gcloud services enable run.googleapis.com \
    cloudbuild.googleapis.com \
    secretmanager.googleapis.com \
    artifactregistry.googleapis.com \
    --project="$PROJECT_ID" --quiet

# ─── Step 2: Create secrets for API keys ───
echo ""
echo "► Setting up secrets in Secret Manager..."

create_secret_if_missing() {
    local name=$1
    local prompt=$2
    if ! gcloud secrets describe "$name" --project="$PROJECT_ID" &>/dev/null; then
        echo "  Creating secret: $name"
        read -sp "  $prompt: " value
        echo ""
        printf "%s" "$value" | gcloud secrets create "$name" \
            --data-file=- --project="$PROJECT_ID" --quiet
    else
        echo "  Secret exists: $name (use gcloud secrets versions add to update)"
    fi
}

create_secret_if_missing "mirofish-llm-api-key" "Enter your OpenAI API key (primary, gpt-4o)"
create_secret_if_missing "mirofish-llm-boost-api-key" "Enter your OpenAI API key (boost, gpt-4o-mini — same key is fine)"
create_secret_if_missing "mirofish-zep-api-key" "Enter your Zep API key (or press Enter to skip)"
create_secret_if_missing "mirofish-databento-api-key" "Enter your Databento API key (db-...)"

# Grant Cloud Run access to secrets
echo "  Granting Cloud Run service account access to secrets..."
SA="${PROJECT_ID}@appspot.gserviceaccount.com"
for secret in mirofish-llm-api-key mirofish-llm-boost-api-key mirofish-zep-api-key mirofish-databento-api-key; do
    gcloud secrets add-iam-policy-binding "$secret" \
        --member="serviceAccount:${SA}" \
        --role="roles/secretmanager.secretAccessor" \
        --project="$PROJECT_ID" --quiet 2>/dev/null || true
done

# ─── Step 3: Create GCS bucket for persistent storage ───
echo ""
BUCKET_NAME="${PROJECT_ID}-mirofish-results"
echo "► Creating GCS bucket: ${BUCKET_NAME} (if not exists)..."
gsutil ls "gs://${BUCKET_NAME}" 2>/dev/null || \
    gsutil mb -l "${REGION}" "gs://${BUCKET_NAME}" 2>/dev/null || \
    echo "  Bucket may already exist or requires manual creation."
echo "  Bucket: gs://${BUCKET_NAME}"

# ─── Step 4: Build and push container ───
echo ""
echo "► Building container image..."
docker build --platform linux/amd64 --provenance=false -f Dockerfile.cloudrun -t "$IMAGE" .

echo "► Pushing to Container Registry..."
docker push "$IMAGE"

# ─── Step 5: Deploy to Cloud Run ───
echo ""
echo "► Deploying to Cloud Run ($REGION)..."
gcloud run deploy "$SERVICE_NAME" \
    --image "$IMAGE" \
    --region "$REGION" \
    --platform managed \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --concurrency 10 \
    --min-instances 0 \
    --max-instances 3 \
    --set-env-vars "PYTHONPATH=/app,PYTHONUNBUFFERED=1,LOG_LEVEL=INFO,LLM_BASE_URL=https://api.openai.com/v1,LLM_MODEL_NAME=gpt-4o,LLM_BOOST_BASE_URL=https://api.openai.com/v1,LLM_BOOST_MODEL_NAME=gpt-4o-mini,GCS_BUCKET=${BUCKET_NAME}" \
    --set-secrets "LLM_API_KEY=mirofish-llm-api-key:latest,LLM_BOOST_API_KEY=mirofish-llm-boost-api-key:latest,ZEP_API_KEY=mirofish-zep-api-key:latest,DATABENTO_API_KEY=mirofish-databento-api-key:latest" \
    --project "$PROJECT_ID" \
    --quiet

# ─── Step 6: Verify ───
echo ""
echo "► Verifying deployment..."
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region "$REGION" --project "$PROJECT_ID" \
    --format="value(status.url)")

echo ""
HEALTH=$(curl -s "${SERVICE_URL}/api/health")
echo "  Health check: $HEALTH"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✓ Deployment complete!                             ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "  Service URL: $SERVICE_URL"
echo "  Health:      ${SERVICE_URL}/api/health"
echo "  Scenarios:   ${SERVICE_URL}/api/scenarios"
echo ""
echo "  Test simulation:"
echo "    curl -X POST ${SERVICE_URL}/api/simulations \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"scenario\": \"scenario_a\", \"seed\": 42}'"
echo ""
echo "  Estimated cost per simulation: \$2-5 (OpenAI tokens)"
echo "  Cloud Run cost: ~\$0 (scale-to-zero when idle)"
echo "╚══════════════════════════════════════════════════════╝"
