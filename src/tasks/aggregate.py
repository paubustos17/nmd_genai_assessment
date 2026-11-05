"""Results aggregation task logic."""

import json
import logging

from common.aws import get_s3_client

logger = logging.getLogger(__name__)


def aggregate_results(event: dict) -> dict:
    """Aggregate extraction results and write summary to S3.

    Collects preprocessing, classification, and extraction results into a summary
    JSON object and writes it to S3 at results/{document_id}.json.

    Args:
        event: Full pipeline state with preprocess, classify, and extract results.

    Returns:
        Summary of the pipeline execution.
    """
    logger.info("Aggregating results")

    preprocess = event.get("preprocess_result", {})
    classify = event.get("classify_result", {})
    extract = event.get("extract_result", {})
    document_id = preprocess.get("document_id", "unknown")
    s3_bucket = preprocess.get("s3_bucket", "")

    summary = {
        "document_id": document_id,
        "document_type": classify.get("document_type", "unknown"),
        "classification_confidence": classify.get("confidence", 0.0),
        "extracted_fields": extract.get("extracted_fields", {}),
        "extraction_confidence": extract.get("confidence", 0.0),
        "status": "completed",
    }

    if not s3_bucket:
        logger.error("No S3 bucket specified for document %s", document_id)
        return summary

    try:
        s3 = get_s3_client()
        s3_key = f"results/{document_id}.json"
        summary_json = json.dumps(summary, indent=2)

        logger.info("Writing summary to s3://%s/%s", s3_bucket, s3_key)
        s3.put_object(Bucket=s3_bucket, Key=s3_key, Body=summary_json, ContentType="application/json")
        logger.info("Successfully wrote results for document %s", document_id)

    except Exception as e:
        logger.error("Failed to write results to S3 for document %s: %s", document_id, str(e))
        raise

    return summary
