"""Document classification task logic using Bedrock LLM."""

import json
import logging
import os

from common.aws import get_bedrock_client
from common.retry import retry_with_backoff

logger = logging.getLogger(__name__)

CLASSIFY_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-5-5")

VALID_DOCUMENT_TYPES = {
    "cybersecurity_advisory",
    "drug_approval",
    "airworthiness_directive",
    "financial_filing",
    "unknown",
}


@retry_with_backoff(max_attempts=3, base_delay=1.0, backoff_multiplier=2.0)
def _call_bedrock_classify(bedrock_client, prompt: str) -> dict:
    """Call Bedrock to classify document using Messages API. Wrapped with retry logic.

    Uses the Anthropic Messages API format for Claude models:
    - anthropic_version: "bedrock-2023-05-31" specifies the API version
    - max_tokens: 256 limits response length to ensure JSON response
    - messages: Array of message objects with role and content
      - role: "user" for user-provided content
      - content: The prompt text requesting JSON response

    Args:
        bedrock_client: Bedrock Runtime client.
        prompt: Prompt text for classification (requests JSON response).

    Returns:
        Parsed JSON response from Bedrock with content array.
        Format: {"content": [{"text": "...json response..."}], ...}

    Raises:
        ClientError: If Bedrock API call fails (caught and retried by decorator).
    """
    # Format request using Anthropic Messages API
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 256,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }

    # Invoke Bedrock model with Messages API format
    response = bedrock_client.invoke_model(
        modelId=CLASSIFY_MODEL_ID,
        body=json.dumps(request_body),
    )

    # Parse response body (contains JSON with content array)
    response_body = json.loads(response["body"].read().decode("utf-8"))
    return response_body


def classify_document(event: dict) -> dict:
    """Classify a document using Bedrock LLM.

    Classifies the document into one of five types: cybersecurity_advisory,
    drug_approval, airworthiness_directive, financial_filing, or unknown.

    Args:
        event: Input with document content from preprocessing.

    Returns:
        Classification result with document_type and confidence (0-1).
    """
    document_id = event["document_id"]
    content = event.get("content", "")
    logger.info("Classifying document: %s", document_id)

    if not content.strip():
        logger.warning("Document %s has empty content, classifying as unknown", document_id)
        return {"document_type": "unknown", "confidence": 0.0}

    prompt = f"""You are a document classifier. Analyze the following document content and classify it into ONE of these types:

1. cybersecurity_advisory - security advisories, CVE notices, threat alerts
2. drug_approval - FDA drug approvals, pharmaceutical regulatory notices
3. airworthiness_directive - aviation safety directives, aircraft maintenance orders
4. financial_filing - SEC filings, financial statements, investor disclosures
5. unknown - if the document doesn't fit any category

Respond ONLY with a JSON object (no markdown, no extra text) in this exact format:
{{
  "type": "<one of the 5 types above>",
  "confidence_percentage": <0-100>,
  "reasoning": "<1-2 sentence explanation>"
}}

Document to classify:
{content}"""

    try:
        bedrock = get_bedrock_client()
        response = _call_bedrock_classify(bedrock, prompt)

        # Extract the text response from Claude
        if "content" not in response or not response["content"]:
            logger.error("No content in Bedrock response for document %s", document_id)
            return {"document_type": "unknown", "confidence": 0.0}

        response_text = response["content"][0].get("text", "").strip()
        logger.debug("Classification response for %s: %s", document_id, response_text)

        # Parse JSON response
        try:
            classification = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse classification JSON for %s: %s", document_id, str(e))
            return {"document_type": "unknown", "confidence": 0.0}

        # Validate and normalize response
        doc_type = classification.get("type", "").lower().strip()
        if doc_type not in VALID_DOCUMENT_TYPES:
            logger.warning(
                "Invalid document type '%s' for %s, using 'unknown'",
                doc_type,
                document_id,
            )
            doc_type = "unknown"

        confidence_pct = classification.get("confidence_percentage", 0)
        confidence = max(0.0, min(1.0, float(confidence_pct) / 100.0))

        logger.info(
            "Classified document %s as %s (confidence: %.2f)",
            document_id,
            doc_type,
            confidence,
        )

        return {"document_type": doc_type, "confidence": confidence}

    except Exception as e:
        logger.error("Classification failed for document %s: %s", document_id, str(e))
        raise
