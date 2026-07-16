# Google Cloud Function to automatically disable Cloud Run service when budget is exceeded.
# Triggered by Pub/Sub message from Google Billing Alerts.

import base64
import json
import logging
from google.apiclient import discovery
from google.auth import default

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = "YOUR_GCP_PROJECT_ID"  # Replace with your GCP Project ID
SERVICE_NAME = "recruiter-app"      # Replace with your Cloud Run Service Name
REGION = "us-central1"              # Replace with your Cloud Run region (e.g. us-central1)


def limit_billing(event, context):
    """Entry point for the Cloud Function. Resolves billing alert and stops Cloud Run."""
    pubsub_message = base64.b64decode(event["data"]).decode("utf-8")
    data = json.loads(pubsub_message)
    
    cost_amount = data.get("costAmount")
    budget_amount = data.get("budgetAmount")
    
    logger.info(f"Billing Alert received: Cost={cost_amount}, Budget={budget_amount}")
    
    # Check if budget is exceeded (or has reached 100% of threshold)
    # The payload contains 'alertThresholdExceeded' (e.g. 1.0 representing 100%)
    threshold = data.get("alertThresholdExceeded")
    if threshold is not None and float(threshold) >= 1.0:
        logger.warning(f"Budget threshold exceeded ({threshold * 100}%). Shutting down Cloud Run service...")
        shutdown_cloud_run()
    else:
        logger.info("Cost is below 100% threshold. No shutdown required.")


def shutdown_cloud_run():
    """Update Cloud Run service maxScale (max-instances) to 0 using Google API Client."""
    credentials, _ = default()
    service = discovery.build("run", "v1", credentials=credentials)
    
    name = f"projects/{PROJECT_ID}/locations/{REGION}/services/{SERVICE_NAME}"
    
    try:
        # Get existing service configuration
        logger.info(f"Fetching configuration for service: {name}")
        request = service.projects().locations().services().get(name=name)
        svc_config = request.execute()
        
        # Modify maxScale metadata to 0
        # Under v1 API, maxScale is stored as an annotation in spec.template.metadata.annotations
        annotations = svc_config.setdefault("spec", {}).setdefault("template", {}).setdefault("metadata", {}).setdefault("annotations", {})
        annotations["autoscaling.knative.dev/maxScale"] = "0"
        
        logger.info("Updating service maxScale to 0 (stopping container)...")
        update_request = service.projects().locations().services().replaceService(name=name, body=svc_config)
        update_request.execute()
        logger.info("✓ Cloud Run service successfully shut down.")
        
    except Exception as e:
        logger.error(f"Failed to shut down Cloud Run service: {e}")
        raise e
