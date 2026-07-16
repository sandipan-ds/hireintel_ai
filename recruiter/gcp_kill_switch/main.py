# Google Cloud Function to automatically disable Cloud Run service when budget is exceeded.
# Triggered by Pub/Sub message from Google Billing Alerts.

import base64
import json
import logging
import os
from googleapiclient import discovery
from google.auth import default

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("billing_kill_switch")

# Initialize GCP Clients using default credentials
auth_credentials, default_project_id = default()
PROJECT_ID = os.environ.get("GCP_PROJECT", default_project_id)
SERVICE_NAME = os.environ.get("SERVICE_NAME", "recruiter-app")
REGION = os.environ.get("GCP_REGION", "us-central1")


def limit_billing(event, context):
    """Entry point for the Cloud Function. Resolves billing alert and stops Cloud Run."""
    if 'data' not in event:
        logger.error("No data found in the Pub/Sub event.")
        return

    # Decode Pub/Sub payload
    pubsub_data = base64.b64decode(event['data']).decode('utf-8')
    logger.info(f"Received billing alert payload: {pubsub_data}")
    
    try:
        data = json.loads(pubsub_data)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Pub/Sub data as JSON: {str(e)}")
        return

    cost_amount = data.get('costAmount', 0.0)
    budget_amount = data.get('budgetAmount', 0.0)
    
    logger.info(f"Current Cost: ${cost_amount:.2f}, Budget Limit: ${budget_amount:.2f}")

    # Check if budget is exceeded (or has reached 100% of threshold)
    threshold = data.get("alertThresholdExceeded")
    is_exceeded = (threshold is not None and float(threshold) >= 1.0) or (budget_amount > 0.0 and cost_amount >= budget_amount)

    if is_exceeded:
        logger.warning(f"CRITICAL: Budget of ${budget_amount:.2f} reached/exceeded with cost ${cost_amount:.2f}! Disabling Cloud Run service...")
        shutdown_cloud_run()
    else:
        logger.info("Cost is below 100% threshold. No shutdown required.")


def shutdown_cloud_run():
    """Update Cloud Run service maxScale (max-instances) to 0 and revoke public invoker IAM policy."""
    service = discovery.build("run", "v1", credentials=auth_credentials)
    name = f"projects/{PROJECT_ID}/locations/{REGION}/services/{SERVICE_NAME}"
    
    try:
        # 1. Fetch current service configuration
        logger.info(f"Fetching configuration for service: {name}")
        request = service.projects().locations().services().get(name=name)
        svc_config = request.execute()
        
        # 2. Modify maxScale metadata to 0 (and minScale to 0 if present)
        template_metadata = svc_config.setdefault("spec", {}).setdefault("template", {}).setdefault("metadata", {})
        annotations = template_metadata.setdefault("annotations", {})
        annotations["autoscaling.knative.dev/maxScale"] = "0"
        if "autoscaling.knative.dev/minScale" in annotations:
            annotations["autoscaling.knative.dev/minScale"] = "0"
        
        logger.info("Updating service maxScale to 0 (stopping container)...")
        update_request = service.projects().locations().services().replaceService(name=name, body=svc_config)
        update_request.execute()
        logger.info("✓ Cloud Run service successfully scaled to 0.")
        
        # 3. Revoke public access by removing 'allUsers' invoker binding
        logger.info(f"Revoking public access for {SERVICE_NAME}...")
        iam_request = service.projects().locations().services().getIamPolicy(resource=name)
        policy = iam_request.execute()
        
        bindings = policy.get('bindings', [])
        modified_bindings = []
        revoked = False
        
        for binding in bindings:
            if binding.get('role') == 'roles/run.invoker':
                members = binding.get('members', [])
                if 'allUsers' in members:
                    members.remove('allUsers')
                    revoked = True
                    logger.info(f"Removed 'allUsers' from roles/run.invoker on {SERVICE_NAME}")
            if binding.get('members'):
                modified_bindings.append(binding)
        
        if revoked:
            policy['bindings'] = modified_bindings
            set_iam_request = service.projects().locations().services().setIamPolicy(
                resource=name,
                body={'policy': policy}
            )
            set_iam_request.execute()
            logger.info("✓ Public invoker access successfully revoked.")
        else:
            logger.info("No public IAM invoker bindings found to revoke.")
            
    except Exception as e:
        logger.error(f"Failed to execute kill switch for Cloud Run service: {e}")
        raise e
