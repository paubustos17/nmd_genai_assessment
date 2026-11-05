"""LLM-based field extraction task logic."""

import json
import logging
import os

from common.aws import get_bedrock_client
from common.retry import retry_with_backoff

logger = logging.getLogger(__name__)

EXTRACT_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-5-5")

# Document type to expected field definitions
FIELD_SPECS = {
    "cybersecurity_advisory": [
        "severity",
        "cve_ids",
        "affected_products",
        "mitigation_steps",
    ],
    "drug_approval": [
        "drug_name",
        "indication",
        "approval_date",
        "applicant",
        "dosage",
    ],
    "airworthiness_directive": [
        "ad_number",
        "affected_aircraft",
        "compliance_deadline",
        "required_action",
    ],
    "financial_filing": [
        "company_name",
        "filing_date",
        "event_type",
        "revenue",
        "net_income",
    ],
}


@retry_with_backoff(max_attempts=3, base_delay=1.0, backoff_multiplier=2.0)
def _call_bedrock_extract(bedrock_client, prompt: str) -> dict:
    """Call Bedrock to extract fields using Messages API. Wrapped with retry logic.

    Uses the Anthropic Messages API format for Claude models:
    - anthropic_version: "bedrock-2023-05-31" specifies the API version
    - max_tokens: 512 limits response length for structured JSON with multiple fields
    - messages: Array of message objects with role and content
      - role: "user" for user-provided content
      - content: The prompt text requesting JSON response with extracted fields

    Args:
        bedrock_client: Bedrock Runtime client.
        prompt: Prompt text for field extraction (requests JSON response).

    Returns:
        Parsed JSON response from Bedrock with content array.
        Format: {"content": [{"text": "...json response..."}], ...}

    Raises:
        ClientError: If Bedrock API call fails (caught and retried by decorator).
    """
    # Format request using Anthropic Messages API
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }

    # Invoke Bedrock model with Messages API format
    response = bedrock_client.invoke_model(
        modelId=EXTRACT_MODEL_ID,
        body=json.dumps(request_body),
    )

    # Parse response body (contains JSON with content array)
    response_body = json.loads(response["body"].read().decode("utf-8"))
    return response_body


def extract_fields(event: dict) -> dict:
    """Extract structured fields from document content using Bedrock.

    If the document type is "unknown", skips extraction and returns empty results.
    Otherwise, calls Bedrock to extract document-type-specific fields.

    Args:
        event: Input with document content and classification.

    Returns:
        Extracted fields as structured data with confidence score.
    """
    document_id = event["document_id"]
    content = event.get("content", "")
    document_type = event.get("document_type", "unknown")
    logger.info("Extracting fields from: %s (type: %s)", document_id, document_type)

    # Skip extraction for unknown document types (per requirement 3=c)
    if document_type == "unknown":
        logger.info("Skipping extraction for unknown document type: %s", document_id)
        return {"extracted_fields": {}, "confidence": 0.0}

    if document_type not in FIELD_SPECS:
        logger.warning(
            "Document type '%s' not in field specs for %s, returning empty",
            document_type,
            document_id,
        )
        return {"extracted_fields": {}, "confidence": 0.0}

    if not content.strip():
        logger.warning("Document %s has empty content, returning empty fields", document_id)
        return {"extracted_fields": {}, "confidence": 0.0}

    field_names = FIELD_SPECS[document_type]
    field_list = ", ".join(field_names)

    prompt = f"""You are a structured data extractor. Extract the following fields from the document content.

Expected fields for document type '{document_type}':
{field_list}

Respond ONLY with a JSON object (no markdown, no extra text) in this exact format:
{{
  "fields": {{
    "field_name": "<extracted value or null if not found>"
  }},
  "extraction_confidence": <0-100>,
  "notes": "<any relevant notes about extraction quality>"
}}

Document content:
{content}"""

    try:
        bedrock = get_bedrock_client()
        response = _call_bedrock_extract(bedrock, prompt)

        # Extract the text response from Claude
        if "content" not in response or not response["content"]:
            logger.error("No content in Bedrock response for document %s", document_id)
            return {"extracted_fields": {}, "confidence": 0.0}

        response_text = response["content"][0].get("text", "").strip()
        logger.debug("Extraction response for %s: %s", document_id, response_text)

        # Parse JSON response
        try:
            extraction = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse extraction JSON for %s: %s", document_id, str(e))
            return {"extracted_fields": {}, "confidence": 0.0}

        # Extract fields and confidence
        extracted_fields = extraction.get("fields", {})
        confidence_pct = extraction.get("extraction_confidence", 0)
        confidence = max(0.0, min(1.0, float(confidence_pct) / 100.0))

        # Ensure all expected fields are present (fill with null if missing)
        for field_name in field_names:
            if field_name not in extracted_fields:
                extracted_fields[field_name] = None

        logger.info(
            "Extracted %d fields from document %s (confidence: %.2f)",
            len(extracted_fields),
            document_id,
            confidence,
        )

        return {"extracted_fields": extracted_fields, "confidence": confidence}

    except Exception as e:
        logger.error("Field extraction failed for document %s: %s", document_id, str(e))
        raise
