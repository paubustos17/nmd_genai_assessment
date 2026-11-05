"""Comprehensive tests for task functions."""

import json
from unittest.mock import MagicMock

import pytest

from tasks.classify import classify_document
from tasks.extract import extract_fields
from tasks.aggregate import aggregate_results
from tasks.preprocess import preprocess_document
from common.retry import retry_with_backoff
from botocore.exceptions import ClientError


class TestRetryDecorator:
    """Tests for the retry_with_backoff decorator."""

    def test_retry_succeeds_on_first_attempt(self):
        """Function succeeds immediately without retry."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, base_delay=0.01, backoff_multiplier=2.0)
        def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = success_func()
        assert result == "success"
        assert call_count == 1

    def test_retry_succeeds_on_second_attempt(self):
        """Function retries once then succeeds."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, base_delay=0.01, backoff_multiplier=2.0)
        def eventually_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ClientError({"Error": {"Code": "ThrottlingException"}}, "InvokeModel")
            return "success"

        result = eventually_succeeds()
        assert result == "success"
        assert call_count == 2

    def test_retry_fails_after_max_attempts(self):
        """Function fails after exhausting max attempts."""
        call_count = 0

        @retry_with_backoff(max_attempts=2, base_delay=0.01, backoff_multiplier=2.0)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ClientError({"Error": {"Code": "ThrottlingException"}}, "InvokeModel")

        with pytest.raises(ClientError):
            always_fails()

        assert call_count == 2

    def test_retry_respects_max_attempts_parameter(self):
        """Decorator respects custom max_attempts."""
        call_count = 0

        @retry_with_backoff(max_attempts=5, base_delay=0.01, backoff_multiplier=2.0)
        def fails_many_times():
            nonlocal call_count
            call_count += 1
            raise ClientError({"Error": {"Code": "ThrottlingException"}}, "InvokeModel")

        with pytest.raises(ClientError):
            fails_many_times()

        assert call_count == 5


class TestClassify:
    """Tests for the classify_document task."""

    def test_classify_cybersecurity_advisory(self, mocker):
        """Classify cybersecurity advisory correctly."""
        mock_bedrock = mocker.patch("tasks.classify.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        # Mock Bedrock response
        bedrock_response = {
            "content": [
                {
                    "text": json.dumps({
                        "type": "cybersecurity_advisory",
                        "confidence_percentage": 98,
                        "reasoning": "Contains CVE mentions and threat information"
                    })
                }
            ]
        }
        mock_client.invoke_model.return_value = {
            "body": MagicMock(read=MagicMock(return_value=json.dumps(bedrock_response).encode()))
        }

        event = {
            "document_id": "test-doc",
            "content": "CVE-2023-27997 heap buffer overflow in FortiGate SSL-VPN"
        }

        result = classify_document(event)

        assert result["document_type"] == "cybersecurity_advisory"
        assert result["confidence"] == 0.98
        assert 0.0 <= result["confidence"] <= 1.0

    def test_classify_drug_approval(self, mocker):
        """Classify drug approval correctly."""
        mock_bedrock = mocker.patch("tasks.classify.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        bedrock_response = {
            "content": [
                {
                    "text": json.dumps({
                        "type": "drug_approval",
                        "confidence_percentage": 95,
                        "reasoning": "FDA approval letter with dosage information"
                    })
                }
            ]
        }
        mock_client.invoke_model.return_value = {
            "body": MagicMock(read=MagicMock(return_value=json.dumps(bedrock_response).encode()))
        }

        event = {
            "document_id": "drug-test",
            "content": "FDA Approval Letter: LUXTERA (miravimod) 6mg and 12mg oral tablet"
        }

        result = classify_document(event)

        assert result["document_type"] == "drug_approval"
        assert result["confidence"] == 0.95

    def test_classify_empty_content_returns_unknown(self, mocker):
        """Empty document content classified as unknown."""
        mock_bedrock = mocker.patch("tasks.classify.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        event = {
            "document_id": "empty-doc",
            "content": ""
        }

        result = classify_document(event)

        assert result["document_type"] == "unknown"
        assert result["confidence"] == 0.0
        # Bedrock should NOT be called for empty content
        mock_client.invoke_model.assert_not_called()

    def test_classify_invalid_type_normalized_to_unknown(self, mocker):
        """Invalid classification type normalized to 'unknown'."""
        mock_bedrock = mocker.patch("tasks.classify.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        bedrock_response = {
            "content": [
                {
                    "text": json.dumps({
                        "type": "invalid_type_xyz",
                        "confidence_percentage": 75,
                        "reasoning": "Bad type from LLM"
                    })
                }
            ]
        }
        mock_client.invoke_model.return_value = {
            "body": MagicMock(read=MagicMock(return_value=json.dumps(bedrock_response).encode()))
        }

        event = {
            "document_id": "bad-type-doc",
            "content": "Some document content"
        }

        result = classify_document(event)

        assert result["document_type"] == "unknown"

    def test_classify_confidence_normalization(self, mocker):
        """Confidence percentage correctly normalized to 0-1 scale."""
        mock_bedrock = mocker.patch("tasks.classify.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        bedrock_response = {
            "content": [
                {
                    "text": json.dumps({
                        "type": "financial_filing",
                        "confidence_percentage": 50,
                        "reasoning": "Borderline classification"
                    })
                }
            ]
        }
        mock_client.invoke_model.return_value = {
            "body": MagicMock(read=MagicMock(return_value=json.dumps(bedrock_response).encode()))
        }

        event = {
            "document_id": "confidence-test",
            "content": "Financial report content"
        }

        result = classify_document(event)

        assert result["confidence"] == 0.5

    def test_classify_malformed_json_returns_unknown(self, mocker):
        """Malformed JSON response handled gracefully."""
        mock_bedrock = mocker.patch("tasks.classify.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        bedrock_response = {
            "content": [
                {
                    "text": "{ invalid json }"
                }
            ]
        }
        mock_client.invoke_model.return_value = {
            "body": MagicMock(read=MagicMock(return_value=json.dumps(bedrock_response).encode()))
        }

        event = {
            "document_id": "malformed-doc",
            "content": "Some content"
        }

        result = classify_document(event)

        assert result["document_type"] == "unknown"
        assert result["confidence"] == 0.0

    def test_classify_missing_content_field(self, mocker):
        """Missing content field handled gracefully."""
        mock_bedrock = mocker.patch("tasks.classify.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        event = {
            "document_id": "no-content-doc"
        }

        result = classify_document(event)

        assert result["document_type"] == "unknown"
        assert result["confidence"] == 0.0


class TestExtract:
    """Tests for the extract_fields task."""

    def test_extract_cybersecurity_fields(self, mocker):
        """Extract cybersecurity advisory fields correctly."""
        mock_bedrock = mocker.patch("tasks.extract.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        bedrock_response = {
            "content": [
                {
                    "text": json.dumps({
                        "fields": {
                            "severity": "Critical",
                            "cve_ids": ["CVE-2023-27997", "CVE-2024-20359"],
                            "affected_products": ["FortiGate SSL-VPN", "Cisco ASA"],
                            "mitigation_steps": ["Apply patches", "Reset credentials", "Enable MFA"]
                        },
                        "extraction_confidence": 94,
                        "notes": "All fields clearly present in document"
                    })
                }
            ]
        }
        mock_client.invoke_model.return_value = {
            "body": MagicMock(read=MagicMock(return_value=json.dumps(bedrock_response).encode()))
        }

        event = {
            "document_id": "cisa-advisory",
            "content": "CISA advisory with CVE-2023-27997...",
            "document_type": "cybersecurity_advisory"
        }

        result = extract_fields(event)

        assert result["extracted_fields"]["severity"] == "Critical"
        assert "CVE-2023-27997" in result["extracted_fields"]["cve_ids"]
        assert result["confidence"] == 0.94

    def test_extract_drug_approval_fields(self, mocker):
        """Extract drug approval fields correctly."""
        mock_bedrock = mocker.patch("tasks.extract.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        bedrock_response = {
            "content": [
                {
                    "text": json.dumps({
                        "fields": {
                            "drug_name": "LUXTERA (miravimod)",
                            "indication": "moderate-to-severe plaque psoriasis",
                            "approval_date": "2024-06-15",
                            "applicant": "Meridian Pharmaceuticals Inc.",
                            "dosage": "6 mg and 12 mg oral tablets"
                        },
                        "extraction_confidence": 96,
                        "notes": "Approval details clearly stated"
                    })
                }
            ]
        }
        mock_client.invoke_model.return_value = {
            "body": MagicMock(read=MagicMock(return_value=json.dumps(bedrock_response).encode()))
        }

        event = {
            "document_id": "fda-approval",
            "content": "FDA Approval: LUXTERA...",
            "document_type": "drug_approval"
        }

        result = extract_fields(event)

        assert result["extracted_fields"]["drug_name"] == "LUXTERA (miravimod)"
        assert result["extracted_fields"]["approval_date"] == "2024-06-15"
        assert result["confidence"] == 0.96

    def test_extract_skips_unknown_document_type(self, mocker):
        """Extraction skipped for unknown document types (no Bedrock call)."""
        mock_bedrock = mocker.patch("tasks.extract.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        event = {
            "document_id": "unknown-doc",
            "content": "Some random content",
            "document_type": "unknown"
        }

        result = extract_fields(event)

        assert result["extracted_fields"] == {}
        assert result["confidence"] == 0.0
        # Bedrock should NOT be called for unknown document type
        mock_client.invoke_model.assert_not_called()

    def test_extract_ensures_all_fields_present(self, mocker):
        """Missing fields filled with null."""
        mock_bedrock = mocker.patch("tasks.extract.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        bedrock_response = {
            "content": [
                {
                    "text": json.dumps({
                        "fields": {
                            "drug_name": "TestDrug",
                            "indication": "Test indication"
                            # Missing: approval_date, applicant, dosage
                        },
                        "extraction_confidence": 65,
                        "notes": "Only partial information found"
                    })
                }
            ]
        }
        mock_client.invoke_model.return_value = {
            "body": MagicMock(read=MagicMock(return_value=json.dumps(bedrock_response).encode()))
        }

        event = {
            "document_id": "partial-drug",
            "content": "Partial drug information...",
            "document_type": "drug_approval"
        }

        result = extract_fields(event)

        # All expected fields should be present
        assert "drug_name" in result["extracted_fields"]
        assert "indication" in result["extracted_fields"]
        assert "approval_date" in result["extracted_fields"]
        assert "applicant" in result["extracted_fields"]
        assert "dosage" in result["extracted_fields"]
        # Missing fields should be null
        assert result["extracted_fields"]["approval_date"] is None
        assert result["extracted_fields"]["applicant"] is None

    def test_extract_confidence_normalization(self, mocker):
        """Confidence percentage normalized to 0-1 scale."""
        mock_bedrock = mocker.patch("tasks.extract.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        bedrock_response = {
            "content": [
                {
                    "text": json.dumps({
                        "fields": {
                            "ad_number": "AD-2024-001",
                            "affected_aircraft": "Boeing 737",
                            "compliance_deadline": "2024-12-01",
                            "required_action": "Inspection required"
                        },
                        "extraction_confidence": 75,
                        "notes": "Good extraction"
                    })
                }
            ]
        }
        mock_client.invoke_model.return_value = {
            "body": MagicMock(read=MagicMock(return_value=json.dumps(bedrock_response).encode()))
        }

        event = {
            "document_id": "airworthiness",
            "content": "Airworthiness directive...",
            "document_type": "airworthiness_directive"
        }

        result = extract_fields(event)

        assert result["confidence"] == 0.75

    def test_extract_malformed_json_returns_empty(self, mocker):
        """Malformed JSON response handled gracefully."""
        mock_bedrock = mocker.patch("tasks.extract.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        bedrock_response = {
            "content": [
                {
                    "text": "{ bad json"
                }
            ]
        }
        mock_client.invoke_model.return_value = {
            "body": MagicMock(read=MagicMock(return_value=json.dumps(bedrock_response).encode()))
        }

        event = {
            "document_id": "malformed",
            "content": "Content...",
            "document_type": "financial_filing"
        }

        result = extract_fields(event)

        assert result["extracted_fields"] == {}
        assert result["confidence"] == 0.0

    def test_extract_empty_content_returns_empty(self, mocker):
        """Empty content handled gracefully."""
        mock_bedrock = mocker.patch("tasks.extract.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        event = {
            "document_id": "empty",
            "content": "",
            "document_type": "drug_approval"
        }

        result = extract_fields(event)

        assert result["extracted_fields"] == {}
        assert result["confidence"] == 0.0
        # Bedrock should NOT be called for empty content
        mock_client.invoke_model.assert_not_called()

    def test_extract_missing_document_type(self, mocker):
        """Missing document_type defaults to unknown (skips extraction)."""
        mock_bedrock = mocker.patch("tasks.extract.get_bedrock_client")
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        event = {
            "document_id": "no-type",
            "content": "Some content"
            # Missing: document_type
        }

        result = extract_fields(event)

        assert result["extracted_fields"] == {}
        assert result["confidence"] == 0.0
        mock_client.invoke_model.assert_not_called()


class TestAggregate:
    """Tests for the aggregate_results task."""

    def test_aggregate_combines_all_results(self, mocker):
        """Aggregate combines preprocessing, classification, and extraction results."""
        mock_s3 = mocker.patch("tasks.aggregate.get_s3_client")
        mock_client = MagicMock()
        mock_s3.return_value = mock_client

        event = {
            "preprocess_result": {
                "document_id": "test-doc",
                "s3_bucket": "test-bucket",
                "title": "Test Document",
                "content": "Test content",
                "source": "Test Source",
                "date": "2024-11-03"
            },
            "classify_result": {
                "document_type": "cybersecurity_advisory",
                "confidence": 0.95
            },
            "extract_result": {
                "extracted_fields": {
                    "severity": "Critical",
                    "cve_ids": ["CVE-2024-001"],
                    "affected_products": ["Product A"],
                    "mitigation_steps": ["Step 1", "Step 2"]
                },
                "confidence": 0.92
            }
        }

        result = aggregate_results(event)

        assert result["document_id"] == "test-doc"
        assert result["document_type"] == "cybersecurity_advisory"
        assert result["classification_confidence"] == 0.95
        assert result["extraction_confidence"] == 0.92
        assert result["extracted_fields"]["severity"] == "Critical"
        assert result["status"] == "completed"

    def test_aggregate_writes_to_s3(self, mocker):
        """Aggregate writes summary JSON to S3."""
        mock_s3 = mocker.patch("tasks.aggregate.get_s3_client")
        mock_client = MagicMock()
        mock_s3.return_value = mock_client

        event = {
            "preprocess_result": {
                "document_id": "doc123",
                "s3_bucket": "my-bucket",
                "title": "Title",
                "content": "Content",
                "source": "Source",
                "date": "2024-11-03"
            },
            "classify_result": {
                "document_type": "drug_approval",
                "confidence": 0.88
            },
            "extract_result": {
                "extracted_fields": {"drug_name": "DrugX"},
                "confidence": 0.85
            }
        }

        result = aggregate_results(event)

        # Verify S3 put_object was called
        mock_client.put_object.assert_called_once()
        call_args = mock_client.put_object.call_args

        # Verify S3 key and bucket
        assert call_args[1]["Bucket"] == "my-bucket"
        assert call_args[1]["Key"] == "results/doc123.json"
        assert call_args[1]["ContentType"] == "application/json"

        # Verify body is valid JSON
        body_json = json.loads(call_args[1]["Body"])
        assert body_json["document_id"] == "doc123"
        assert body_json["document_type"] == "drug_approval"

    def test_aggregate_handles_missing_s3_bucket(self, mocker):
        """Aggregate handles missing S3 bucket gracefully."""
        mock_s3 = mocker.patch("tasks.aggregate.get_s3_client")
        mock_client = MagicMock()
        mock_s3.return_value = mock_client

        event = {
            "preprocess_result": {
                "document_id": "doc-no-bucket",
                "s3_bucket": "",
                "title": "Title",
                "content": "Content",
                "source": "Source",
                "date": "2024-11-03"
            },
            "classify_result": {
                "document_type": "financial_filing",
                "confidence": 0.90
            },
            "extract_result": {
                "extracted_fields": {"company_name": "CompanyX"},
                "confidence": 0.88
            }
        }

        result = aggregate_results(event)

        # Should return summary even if S3 bucket missing
        assert result["document_id"] == "doc-no-bucket"
        # S3 put_object should NOT be called
        mock_client.put_object.assert_not_called()

    def test_aggregate_handles_missing_results(self, mocker):
        """Aggregate handles missing result sections gracefully."""
        mock_s3 = mocker.patch("tasks.aggregate.get_s3_client")
        mock_client = MagicMock()
        mock_s3.return_value = mock_client

        event = {
            "preprocess_result": {
                "document_id": "incomplete-doc",
                "s3_bucket": "bucket",
                "title": "Title",
                "content": "Content",
                "source": "Source",
                "date": "2024-11-03"
            }
            # Missing: classify_result and extract_result
        }

        result = aggregate_results(event)

        assert result["document_id"] == "incomplete-doc"
        assert result["document_type"] == "unknown"
        assert result["classification_confidence"] == 0.0
        assert result["extracted_fields"] == {}
        assert result["extraction_confidence"] == 0.0

    def test_aggregate_default_document_id(self, mocker):
        """Aggregate uses 'unknown' if document_id missing."""
        mock_s3 = mocker.patch("tasks.aggregate.get_s3_client")
        mock_client = MagicMock()
        mock_s3.return_value = mock_client

        event = {
            "preprocess_result": {
                "s3_bucket": "bucket"
                # Missing: document_id
            },
            "classify_result": {
                "document_type": "cybersecurity_advisory",
                "confidence": 0.90
            },
            "extract_result": {
                "extracted_fields": {},
                "confidence": 0.0
            }
        }

        result = aggregate_results(event)

        assert result["document_id"] == "unknown"

    def test_aggregate_result_structure(self, mocker):
        """Aggregate result has all required fields."""
        mock_s3 = mocker.patch("tasks.aggregate.get_s3_client")
        mock_client = MagicMock()
        mock_s3.return_value = mock_client

        event = {
            "preprocess_result": {
                "document_id": "test",
                "s3_bucket": "bucket",
                "title": "Title",
                "content": "Content",
                "source": "Source",
                "date": "2024-11-03"
            },
            "classify_result": {
                "document_type": "airworthiness_directive",
                "confidence": 0.87
            },
            "extract_result": {
                "extracted_fields": {"ad_number": "AD-001"},
                "confidence": 0.83
            }
        }

        result = aggregate_results(event)

        # Verify all required fields present
        assert "document_id" in result
        assert "document_type" in result
        assert "classification_confidence" in result
        assert "extracted_fields" in result
        assert "extraction_confidence" in result
        assert "status" in result
        assert result["status"] == "completed"


class TestPreprocess:
    """Tests for the preprocess task."""

    def test_preprocess_returns_document_id(self, mocker):
        """Preprocess should extract document_id from s3_key."""
        mock_s3 = mocker.patch("tasks.preprocess.get_s3_client")
        mock_client = MagicMock()
        mock_s3.return_value = mock_client

        # Mock S3 response
        doc_content = {
            "title": "Test Title",
            "content": "Test content",
            "source": "Test Source",
            "date": "2024-11-03"
        }
        mock_client.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(
                return_value=json.dumps(doc_content).encode("utf-8")
            ))
        }

        event = {
            "s3_bucket": "test-bucket",
            "s3_key": "uploads/test-document.json"
        }

        result = preprocess_document(event)

        assert result["document_id"] == "test-document"

    def test_preprocess_extracts_metadata(self, mocker):
        """Preprocess extracts all document metadata."""
        mock_s3 = mocker.patch("tasks.preprocess.get_s3_client")
        mock_client = MagicMock()
        mock_s3.return_value = mock_client

        doc_content = {
            "title": "Security Advisory",
            "content": "Critical vulnerability details",
            "source": "CISA",
            "date": "2024-11-03"
        }
        mock_client.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(
                return_value=json.dumps(doc_content).encode("utf-8")
            ))
        }

        event = {
            "s3_bucket": "docs-bucket",
            "s3_key": "uploads/security-advisory.json"
        }

        result = preprocess_document(event)

        assert result["title"] == "Security Advisory"
        assert result["content"] == "Critical vulnerability details"
        assert result["source"] == "CISA"
        assert result["date"] == "2024-11-03"
        assert result["status"] == "preprocessed"

