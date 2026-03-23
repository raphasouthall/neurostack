# NeuroStack Cloud deployment targets — GCP-only stack
# Usage: make deploy (deploys everything)
# Prerequisites: gcloud CLI authenticated, .env file with GCP_PROJECT_ID

.PHONY: deploy deploy-storage deploy-secrets deploy-api deploy-frontend deploy-firebase-init deploy-all status logs-api doctor

# Load .env if it exists
-include cloud/.env

GCP_PROJECT ?= $(GCP_PROJECT_ID)
GCP_REGION  ?= us-central1
GCS_BUCKET  ?= $(NEUROSTACK_CLOUD_GCS_BUCKET_NAME)
SERVICE     ?= neurostack-api

## Full deployment
deploy: deploy-storage deploy-secrets deploy-api  ## Deploy all cloud infrastructure

## Create GCS bucket (idempotent)
deploy-storage:
	@echo "Creating GCS bucket $(GCS_BUCKET)..."
	gcloud storage buckets create gs://$(GCS_BUCKET) \
		--project=$(GCP_PROJECT) \
		--location=$(GCP_REGION) \
		--uniform-bucket-level-access 2>/dev/null || echo "Bucket already exists"

## Push secrets to GCP Secret Manager
deploy-secrets:
	@echo "Pushing secrets to GCP Secret Manager..."
	@echo -n "$(NEUROSTACK_CLOUD_GEMINI_API_KEY)" | gcloud secrets create gemini-api-key --data-file=- --project=$(GCP_PROJECT) 2>/dev/null || \
		echo -n "$(NEUROSTACK_CLOUD_GEMINI_API_KEY)" | gcloud secrets versions add gemini-api-key --data-file=- --project=$(GCP_PROJECT)
	@echo -n '$(NEUROSTACK_CLOUD_API_KEYS)' | gcloud secrets create cloud-api-keys --data-file=- --project=$(GCP_PROJECT) 2>/dev/null || \
		echo -n '$(NEUROSTACK_CLOUD_API_KEYS)' | gcloud secrets versions add cloud-api-keys --data-file=- --project=$(GCP_PROJECT)
	@echo -n "$(STRIPE_SECRET_KEY)" | gcloud secrets create stripe-secret-key --data-file=- --project=$(GCP_PROJECT) 2>/dev/null || \
		echo -n "$(STRIPE_SECRET_KEY)" | gcloud secrets versions add stripe-secret-key --data-file=- --project=$(GCP_PROJECT)
	@echo -n "$(STRIPE_WEBHOOK_SECRET)" | gcloud secrets create stripe-webhook-secret --data-file=- --project=$(GCP_PROJECT) 2>/dev/null || \
		echo -n "$(STRIPE_WEBHOOK_SECRET)" | gcloud secrets versions add stripe-webhook-secret --data-file=- --project=$(GCP_PROJECT)

## Deploy Cloud Run service
deploy-api:
	@echo "Deploying Cloud Run service..."
	gcloud run deploy $(SERVICE) \
		--source . \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--allow-unauthenticated \
		--min-instances 0 \
		--max-instances 5 \
		--memory 2Gi \
		--cpu 2 \
		--timeout 300 \
		--no-cpu-throttling \
		--set-env-vars "NEUROSTACK_CLOUD_GCP_PROJECT=$(GCP_PROJECT),NEUROSTACK_CLOUD_GCP_REGION=$(GCP_REGION),NEUROSTACK_CLOUD_GCS_BUCKET_NAME=$(GCS_BUCKET),STRIPE_PRICE_PRO=price_1TE6M5JMyXpOiPfvVJb68GvE,STRIPE_PRICE_TEAM=price_1TE6MKJMyXpOiPfvUf59xVt3" \
		--set-secrets "NEUROSTACK_CLOUD_GEMINI_API_KEY=gemini-api-key:latest,NEUROSTACK_CLOUD_API_KEYS=cloud-api-keys:latest,STRIPE_SECRET_KEY=stripe-secret-key:latest,STRIPE_WEBHOOK_SECRET=stripe-webhook-secret:latest"

## Build and deploy SvelteKit frontend to Firebase Hosting
deploy-frontend:
	@echo "Building SvelteKit frontend..."
	cd frontend && npm ci && npm run build
	@echo "Deploying to Firebase Hosting..."
	firebase deploy --only hosting --project $(GCP_PROJECT)

## Initialize Firebase project (run once)
deploy-firebase-init:
	@echo "Enabling Firebase APIs..."
	gcloud services enable firebase.googleapis.com --project=$(GCP_PROJECT)
	gcloud services enable identitytoolkit.googleapis.com --project=$(GCP_PROJECT)
	gcloud services enable firestore.googleapis.com --project=$(GCP_PROJECT)
	@echo "Firebase APIs enabled. Complete setup in Firebase Console."

## Full deployment (API + Frontend)
deploy-all: deploy deploy-frontend  ## Deploy Cloud Run API and Firebase Hosting frontend

## Show service status
status:
	@echo "=== Cloud Run ==="
	gcloud run services describe $(SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="table(status.url, status.conditions[0].status)"
	@echo ""
	@echo "=== GCS Bucket ==="
	gcloud storage ls gs://$(GCS_BUCKET) --project=$(GCP_PROJECT) 2>/dev/null && echo "  $(GCS_BUCKET): OK" || echo "  $(GCS_BUCKET): NOT FOUND"

## Tail Cloud Run logs
logs-api:
	gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=$(SERVICE)" \
		--limit 50 --project $(GCP_PROJECT) --format="table(timestamp, textPayload)"

## Verify all credentials and connectivity
doctor:
	@echo "Checking gcloud auth..."
	@gcloud auth print-access-token > /dev/null 2>&1 && echo "  gcloud: OK" || echo "  gcloud: FAILED (run: gcloud auth login)"
	@echo "Checking GCP project..."
	@gcloud projects describe $(GCP_PROJECT) > /dev/null 2>&1 && echo "  project $(GCP_PROJECT): OK" || echo "  project $(GCP_PROJECT): NOT FOUND"
	@echo "Checking Vertex AI API..."
	@gcloud services list --enabled --project=$(GCP_PROJECT) --filter="name:aiplatform.googleapis.com" --format="value(name)" | grep -q aiplatform && echo "  Vertex AI: ENABLED" || echo "  Vertex AI: DISABLED (run: gcloud services enable aiplatform.googleapis.com)"
	@echo "Checking Cloud Storage bucket..."
	@gcloud storage ls gs://$(GCS_BUCKET) --project=$(GCP_PROJECT) > /dev/null 2>&1 && echo "  bucket $(GCS_BUCKET): OK" || echo "  bucket $(GCS_BUCKET): NOT FOUND"
