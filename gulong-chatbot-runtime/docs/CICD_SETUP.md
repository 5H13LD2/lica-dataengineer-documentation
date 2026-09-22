# CI/CD Setup

Project: `gulong-chatbot-459723`  
Region: `asia-southeast1`  
Cloud Build connection: `gulong-chat-platform`

## Artifact Registry

Already created:

```powershell
gcloud artifacts repositories create gulong-chatbot-runtime `
  --repository-format=docker `
  --location=asia-southeast1 `
  --description="Gulong chatbot runtime Cloud Run images" `
  --project=gulong-chatbot-459723
```

## Connect the GitHub Repository

After the GitHub repository exists:

```powershell
gcloud builds repositories create gulong-chatbot-runtime `
  --remote-uri=https://github.com/LICA-DataTeam/gulong-chatbot-runtime.git `
  --connection=gulong-chat-platform `
  --region=asia-southeast1 `
  --project=gulong-chatbot-459723
```

Repository resource:

```text
projects/gulong-chatbot-459723/locations/asia-southeast1/connections/gulong-chat-platform/repositories/gulong-chatbot-runtime
```

## Create Cloud Build Triggers

Staging trigger:

```powershell
gcloud builds triggers create github `
  --name=gulong-chatbot-runtime-staging `
  --description="Deploy Gulong chatbot runtime staging from product" `
  --repository=projects/gulong-chatbot-459723/locations/asia-southeast1/connections/gulong-chat-platform/repositories/gulong-chatbot-runtime `
  --branch-pattern="^product$" `
  --build-config=cloudbuild.yaml `
  --region=asia-southeast1 `
  --service-account=projects/gulong-chatbot-459723/serviceAccounts/lica-aids@gulong-chatbot-459723.iam.gserviceaccount.com `
  --include-logs-with-status `
  --substitutions=_SERVICE_NAME=gulong-chatbot-runtime-staging,_SERVICE_ENVIRONMENT=staging,_STATUS=staging,_RUNTIME_DELIVERY_MODE=return_only,_RUNTIME_V7_APPLY_MANYCHAT_TAGS=0,_MAX_INSTANCES=20 `
  --project=gulong-chatbot-459723
```

Do not create a main-branch trigger that deploys a customer-facing Cloud Run
live service. `main` is the approved source for the exact image promoted to the
VM after staging gates pass. Cloud Run remains staging/return-only.

## Manual Trigger Run

```powershell
gcloud builds triggers run gulong-chatbot-runtime-staging `
  --branch=product `
  --region=asia-southeast1 `
  --project=gulong-chatbot-459723
```

The staging trigger must also set `_FOLLOWUP_SEND_ENABLED=false` and
`_FOLLOWUP_SEND_CANARY_PERCENT=0`. `FOLLOWUP_WEBHOOK_TOKEN` is injected from
Secret Manager. A temporary trial send requires a non-empty server-side trial
allowlist and a separate audited deployment; restore send-disabled config after
the trial.
