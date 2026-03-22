# NeuroStack Cloud deployment targets
# Usage: make deploy (deploys everything)
# Prerequisites: gcloud CLI authenticated, wrangler CLI authenticated, .env file with secrets

.PHONY: deploy deploy-storage deploy-secrets deploy-api status logs-api doctor

# Load .env if it exists
-include cloud/.env

GCP_PROJECT ?= $(GCP_PROJECT_ID)
GCP_REGION  ?= us-central1
R2_BUCKET   ?= $(NEUROSTACK_CLOUD_R2_BUCKET_NAME)
SERVICE     ?= neurostack-api

## Full deployment
deploy: deploy-storage deploy-secrets deploy-api  ## Deploy all cloud infrastructure

## Create R2 bucket (idempotent)
deploy-storage:
	@echo "Creating R2 bucket $(R2_BUCKET)..."
	npx wrangler r2 bucket create $(R2_BUCKET) 2>/dev/null || echo "Bucket already exists"

## Push secrets to GCP Secret Manager
deploy-secrets:
	@echo "Pushing secrets to GCP Secret Manager..."
	@echo -n "$(NEUROSTACK_CLOUD_R2_ACCESS_KEY_ID)" | gcloud secrets create r2-access-key --data-file=- --project=$(GCP_PROJECT) 2>/dev/null || \
		echo -n "$(NEUROSTACK_CLOUD_R2_ACCESS_KEY_ID)" | gcloud secrets versions add r2-access-key --data-file=- --project=$(GCP_PROJECT)
	@echo -n "$(NEUROSTACK_CLOUD_R2_SECRET_ACCESS_KEY)" | gcloud secrets create r2-secret-key --data-file=- --project=$(GCP_PROJECT) 2>/dev/null || \
		echo -n "$(NEUROSTACK_CLOUD_R2_SECRET_ACCESS_KEY)" | gcloud secrets versions add r2-secret-key --data-file=- --project=$(GCP_PROJECT)
	@echo -n "$(NEUROSTACK_CLOUD_FIREWORKS_API_KEY)" | gcloud secrets create fireworks-api-key --data-file=- --project=$(GCP_PROJECT) 2>/dev/null || \
		echo -n "$(NEUROSTACK_CLOUD_FIREWORKS_API_KEY)" | gcloud secrets versions add fireworks-api-key --data-file=- --project=$(GCP_PROJECT)
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
		--set-env-vars "NEUROSTACK_CLOUD_R2_ACCOUNT_ID=$(NEUROSTACK_CLOUD_R2_ACCOUNT_ID),NEUROSTACK_CLOUD_R2_BUCKET_NAME=$(R2_BUCKET),NEUROSTACK_CLOUD_FIREWORKS_EMBED_MODEL=$(NEUROSTACK_CLOUD_FIREWORKS_EMBED_MODEL),NEUROSTACK_CLOUD_FIREWORKS_LLM_MODEL=$(NEUROSTACK_CLOUD_FIREWORKS_LLM_MODEL)" \
		--set-secrets "NEUROSTACK_CLOUD_R2_ACCESS_KEY_ID=r2-access-key:latest,NEUROSTACK_CLOUD_R2_SECRET_ACCESS_KEY=r2-secret-key:latest,NEUROSTACK_CLOUD_FIREWORKS_API_KEY=fireworks-api-key:latest,NEUROSTACK_CLOUD_API_KEYS=cloud-api-keys:latest"

## Show service status
status:
	@echo "=== Cloud Run ==="
	gcloud run services describe $(SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="table(status.url, status.conditions[0].status)"
	@echo ""
	@echo "=== R2 Bucket ==="
	npx wrangler r2 bucket list 2>/dev/null | grep $(R2_BUCKET) || echo "Bucket not found"

## Tail Cloud Run logs
logs-api:
	gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=$(SERVICE)" \
		--limit 50 --project $(GCP_PROJECT) --format="table(timestamp, textPayload)"

## Verify all credentials and connectivity
doctor:
	@echo "Checking gcloud auth..."
	@gcloud auth print-access-token > /dev/null 2>&1 && echo "  gcloud: OK" || echo "  gcloud: FAILED (run: gcloud auth login)"
	@echo "Checking wrangler auth..."
	@npx wrangler r2 bucket list > /dev/null 2>&1 && echo "  wrangler: OK" || echo "  wrangler: FAILED (run: npx wrangler login)"
	@echo "Checking GCP project..."
	@gcloud projects describe $(GCP_PROJECT) > /dev/null 2>&1 && echo "  project $(GCP_PROJECT): OK" || echo "  project $(GCP_PROJECT): NOT FOUND"
