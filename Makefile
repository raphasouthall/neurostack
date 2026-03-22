# NeuroStack Cloud deployment targets — GCP-only stack
# Usage: make deploy (deploys everything)
# Prerequisites: gcloud CLI authenticated, .env file with GCP_PROJECT_ID

.PHONY: deploy deploy-storage deploy-secrets deploy-api status logs-api doctor

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
	@echo -n '$(NEUROSTACK_CLOUD_API_KEYS)' | gcloud secrets create cloud-api-keys --data-file=- --project=$(GCP_PROJECT) 2>/dev/null || \
		echo -n '$(NEUROSTACK_CLOUD_API_KEYS)' | gcloud secrets versions add cloud-api-keys --data-file=- --project=$(GCP_PROJECT)

## Deploy Cloud Run service
deploy-api:
	@echo "Deploying Cloud Run service..."
	gcloud run deploy $(SERVICE) \
		--source . \
		--dockerfile cloud/Dockerfile \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--allow-unauthenticated \
		--min-instances 0 \
		--max-instances 5 \
		--memory 1Gi \
		--cpu 1 \
		--timeout 300 \
		--set-env-vars "NEUROSTACK_CLOUD_GCP_PROJECT=$(GCP_PROJECT),NEUROSTACK_CLOUD_GCP_REGION=$(GCP_REGION),NEUROSTACK_CLOUD_GCS_BUCKET_NAME=$(GCS_BUCKET)" \
		--set-secrets "NEUROSTACK_CLOUD_API_KEYS=cloud-api-keys:latest"

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
