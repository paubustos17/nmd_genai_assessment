# Discussion Questions

Answer the **Shared Questions** section plus the **one track section** specified in your email (Solutions Architect OR Data Engineer). 

Aim for 2-4 sentences per answer unless otherwise noted. We value clarity and depth over length.

---

## Shared Questions (everyone answers)

### 1. Troubleshooting

If you could not complete the assessment or got stuck at any point, what went wrong and what did you try to troubleshoot?

**Your answer:**

The implementation completed successfully end-to-end without major blockers. During development, I utilized AI code assistants effectively for prompt optimization and Lambda function implementations, which significantly accelerated the development cycle. The only problem I encountered was deployment and pushing code changes to AWS and Docker — specifically navigating the containerization process, ECR repository setup, and Terraform configurations for the Lambda functions. Although unfamiliar with these deployment commands and workflows initially, I worked through the issues systematically and successfully deployed the pipeline to AWS. This experience reinforced the value of AI assistance for code generation while highlighting the importance of understanding deployment infrastructure and container orchestration in production systems.

### 2. Proof of Completion

Paste the S3 URI to one of your result files (e.g., `s3://nmd-genai-<your-name>-documents/results/<document-id>.json`).

**Your answer:**

s3://nmd-genai-pauline-bustos-documents/results/financial-filing.json

Successfully deployed to AWS using Docker, ECR, Lambda, and Step Functions. The pipeline processed documents end-to-end and stored results in S3 with the architecture defined in Terraform, demonstrating that despite initial unfamiliarity with deployment workflows, the infrastructure-as-code approach allowed for reliable, reproducible deployments.

### 3. Prompt Engineering

How would you improve the classification prompt to handle ambiguous documents that could match multiple types? What techniques would you use to ensure consistent JSON output from the LLM?

**Your answer:**

For ambiguous documents, I'd implement a **multi-level decision approach**: (1) classify at increasing specificity levels (industry → regulatory category → document type) and return confidence scores for each, (2) establish a confidence threshold (e.g., >0.85 for confident classification), and (3) for borderline cases (0.50-0.85), implement a secondary classifier step or flag for human review. For JSON consistency, I'd use: (1) explicit schema specification in the prompt with field types and constraints, (2) few-shot examples showing expected format for edge cases, (3) response validation with JSON schema and fallback retry if parsing fails, and (4) leverage Bedrock's structured output support when available. I used AI assistants to generate these validation patterns and retry logic, which accelerated development significantly. The key learning was that AI-generated code for prompt templates and parsing required hands-on testing to ensure reliable JSON output in production scenarios.

### 4. Error Handling

How would you handle Bedrock throttling (429 errors) in a production pipeline? What retry strategy would you implement, and how would it interact with Step Functions' built-in error handling?

**Your answer:**

I implemented a **two-tier retry strategy**: Application-level retries in Lambda functions using exponential backoff (1s → 2s → 4s, max 3 attempts) to catch transient failures, with the retry logic generated and validated using AI assistance. For Bedrock throttling specifically, I'd detect 429 responses, extract the `Retry-After` header from Bedrock, and sleep accordingly before retrying. In production, I'd monitor CloudWatch metrics (429 error rate, retry frequency) and alert when throttling exceeds 5% of requests, indicating need for provisioned throughput or model capacity scaling. The combination ensures resilience: application retries handle network blips, workflow retries in Step Functions handle downstream system overload. The main learning from deployment was understanding how Lambda timeouts interact with retry logic — ensuring both align to prevent cascading failures in production.

### 5. Enterprise Readiness

Assume a CTO prototyped this pipeline over a weekend using AI code assistants. It works for demos but needs to go to production for a Fortune 500 client.

Write a prioritized list of changes organized by:
1. **Must-fix before production** — what would block a launch?
2. **Should-fix in the first sprint** — what's important but not blocking?
3. **Nice-to-have for long-term maintainability** — what would you plan for later?

Consider security, error handling, observability, testing, CI/CD, and infrastructure hardening.

**Your answer:**

#### **Must-Fix Before Production (Day 1-2)**

1. **Security hardening:** Encrypt S3 buckets with AWS KMS (customer-managed keys), enable CloudTrail for audit logging, scope Lambda IAM roles to least privilege (specific S3 prefixes and Bedrock model IDs only). AI-assisted code generation can produce working solutions but must be reviewed for security configurations.
2. **Input validation & LLM injection prevention:** Validate S3 event payloads, enforce document size limits (>10MB rejected), sanitize content before sending to Bedrock. AI tools helped generate validation logic, but manual security review ensured no bypasses.
3. **Error budget & alerting:** Configure CloudWatch alarms for Lambda error rates >1%, Bedrock throttles, and Step Functions failures; ensure on-call is paged immediately. This requires operational planning beyond code generation.
4. **Dead-letter queue:** Add SQS DLQ to capture failed documents for manual replay and root cause analysis.
5. **Bedrock credential security:** Verify Bedrock data retention policies with AWS; ensure messages aren't stored by default. For PHI, require explicit data handling agreement.
6. **Stress testing & deployment validation:** Validate pipeline handles expected peak load (e.g., 100K docs/day) without Bedrock throttling or Lambda timeouts. This was critical during my deployment phase — testing infrastructure-as-code configurations (Docker, ECR, Lambda, Terraform) in a staging environment before production.

#### **Should-Fix in First Sprint (Week 1-2)**

1. **Comprehensive test coverage:** Unit tests for edge cases (empty content, malformed JSON responses), integration tests with sample documents, schema validation for extracted fields. AI can generate test structure, but domain knowledge ensures coverage of real failure modes.
2. **Monitoring & dashboards:** Build CloudWatch dashboard with classification accuracy by type, extraction confidence distribution, cost per document, and SLA metrics (p99 latency).
3. **Cost governance:** Tag all Bedrock/Lambda invocations with cost center/project; implement cost cap per tenant or runaway cost alerts.
4. **Field validation:** Add JSON schema validation step between Extract and Aggregate; reject responses that don't match expected field types/lengths.
5. **Runbooks & playbooks:** Document operational failures (Bedrock throttling, S3 corruption, Lambda timeout), troubleshooting steps, and escalation procedures. Real-world deployment experience informed these — knowing what actually fails in production.
6. **CI/CD pipeline:** Automate Docker image builds, push to ECR, and Terraform deployments. This was a learning area for me, but essential for reliable infrastructure updates post-launch.

#### **Nice-to-Have for Long-Term Maintainability (Sprint 2+)**

1. **A/B testing framework:** Support comparing classification accuracy across model versions (Haiku vs. Sonnet) or different prompt versions without reprocessing.
2. **Caching & deduplication:** Implement DynamoDB cache keyed on document content hash (SHA256) to avoid redundant Bedrock calls for duplicates; TTL = 30 days.
3. **Batch processing:** Implement Step Functions Map state to parallelize extraction for bulk uploads (Map concurrency = 500), reducing 100K docs from days to minutes.
4. **Cost attribution:** Build per-client cost dashboard with monthly breakdown by service; export for chargeback to customers.
5. **Multi-region replication:** Replicate S3 buckets and Step Functions state machines to secondary AWS region for failover and reduced latency. Infrastructure-as-code (Terraform) makes this repeatable once the primary deployment is validated.
6. **Model fine-tuning:** Collect misclassified documents as training dataset, fine-tune Haiku/Sonnet monthly, benchmark against production model before deploying.

### 6. Terraform — Adding a Pipeline Step

A new "validate" Lambda needs to be added to the pipeline between Extract and Aggregate. It will validate the extracted fields against a schema before writing results. List every file you'd need to change and what you'd add to each.

**Your answer:**

**Files to create/modify:**

1. **`src/tasks/validate.py`** (NEW): Implement `validate_fields(event: dict) -> dict` that takes extracted_fields, validates against JSON schema per document type, returns validation_result with errors or pass status. AI assistance helped scaffold this quickly, but schema design required domain understanding.

2. **`src/lambdas/validate/handler.py`** (NEW): Lambda handler that calls `tasks.validate.validate_fields(event)` and returns result. Following the same pattern as existing handlers, which AI tools replicated consistently.

3. **`terraform/modules/lambda/main.tf`**: Add Lambda function resource for validate (similar to classify, extract, aggregate) with environment variables and timeout configuration. This is where deployment complexity emerges — understanding Terraform syntax, IAM roles, and Lambda layer configuration was critical.

4. **`terraform/modules/lambda/variables.tf`**: Add variables for validate Lambda (function name, timeout, memory, log retention). Terraform variable design benefits from experience with infrastructure provisioning.

5. **`terraform/modules/lambda/outputs.tf`**: Output validate Lambda function name and ARN for state machine reference.

6. **`terraform/modules/step-functions/state_machine.asl.json`** (or equivalent): Modify state machine definition:
   - Add "Validate" task state after Extract
   - Update Extract's Next pointer to "Validate" (was "Aggregate")
   - Update Validate's Next pointer to "Aggregate"
   - Add InputPath to include extract_result in Validate input
   - Add Catch clause to handle validation failures (route to DLQ or human review task)
   This orchestration logic is where the actual deployment workflow lives — getting it right requires testing against real AWS infrastructure.

7. **`terraform/live/candidate/main.tf`**: Add module invocation for validate Lambda with ECR image URI, role, handler config. Here's where I encountered the most learning — understanding how to wire up modules, manage ECR repositories, and coordinate Docker image pushes with Terraform.

8. **`Dockerfile`** (no change): Uses requirements.lambda.txt, works for all handlers.

9. **`requirements.lambda.txt`**: Add `jsonschema>=4.0.0` if needed for schema validation.

10. **`src/tasks/extract.py`** (modify): If using shared schema definitions, import FIELD_SPECS from validate.py or separate schema module. AI-generated code here could introduce circular imports — manual testing during deployment caught these issues.

11. **`.env` and `terraform.tfvars`** (optional): Add validate-specific settings (e.g., SCHEMA_STRICT_MODE=true). Environment management is essential for dev/staging/prod parity.

12. **CI/CD configuration** (NEW): Add build pipeline to automatically build Docker image, push to ECR, and trigger Terraform apply. This was absent from my initial implementation and had to be added manually during deployment.

**Key Insight:** The actual complexity isn't in the code (AI assists well here) — it's in the infrastructure orchestration (Terraform modules, ECR repositories, IAM permissions, Step Functions state machine definitions). Each of these has subtle interdependencies that require hands-on testing in a staging environment before production deployment.

---

## Solutions Architect Track

*Answer this section only if your email specified Solutions Architect.*

### SA-1. Model Selection & Cost Architecture

This assessment restricts you to Claude Haiku. In a production system processing thousands of documents daily, how would you decide which model to use for classification vs. extraction? What factors (cost, latency, accuracy, token limits) would drive that decision? How would you implement cost attribution per client?

**Your answer:**

### SA-2. Security Review

A client wants to process PHI (protected health information) through this pipeline. What changes are needed to meet HIPAA requirements? Think about data at rest, data in transit, Bedrock's data handling policies, IAM scoping, and logging.

**Your answer:**

### SA-3. Multi-Tenancy

A client wants to offer this pipeline as a SaaS feature where each of their customers uploads documents. How would you isolate tenants? Consider S3 partitioning, IAM scoping, cost attribution, and noisy-neighbor protection.

**Your answer:**

### SA-4. Production Readiness Briefing

List the key points you'd convey to a client's VP of Engineering who approved this project but hasn't seen the implementation. What changes are needed before going to production, and how would you prioritize them?

**Your answer:**

---

## Data Engineer Track

*Answer this section only if your email specified Data Engineer.*

### DE-1. Data Quality & Validation

The pipeline trusts the LLM's JSON output without validation. How would you validate extracted fields against a schema? How would you handle extraction failures — retry, dead-letter queue, or flag for human review? What's your strategy?

**Your answer:**

**Validation Approach:**

1. **Schema Definition:** Define JSON Schema per document type:
   ```json
   {
     "cybersecurity_advisory": {
       "severity": {"enum": ["Low", "Medium", "High", "Critical"]},
       "cve_ids": {"type": "array", "items": {"type": "string", "pattern": "^CVE-\\d{4}-\\d{4,}$"}},
       "affected_products": {"type": "array", "minItems": 1},
       "mitigation_steps": {"type": "array"}
     }
   }
   ```

2. **Validation Task:** Add validate Lambda between Extract and Aggregate using `jsonschema` library. Return pass/fail and specific field errors.

3. **Failure Handling Strategy (Tiered):**
   - **Malformed JSON (extract_result parse error):** Send to SQS DLQ immediately. Log raw Bedrock response for debugging. Operations team investigates prompt/model issues.
   - **Schema validation failure + confidence > 0.80:** Retry extraction with stricter prompt including field constraints and examples. Max 1 retry to avoid loops.
   - **Schema validation failure + confidence < 0.70:** Flag for human review (send to SNS topic). Operator validates and manually corrects or marks as unextractable.
   - **Timeout/service error:** Standard exponential backoff retry at Lambda layer.

4. **Long-Term Improvement Loop:**
   - Log all validation failures to DynamoDB with document_id, field_name, LLM output, reason.
   - Weekly, analyze patterns: "Why do we always fail to extract dosage from drug approvals?" Refine prompt accordingly.
   - Track improvement: measure validation success rate trend month-over-month.

This strategy balances automation (fast retry for recoverable issues) with manual intervention (human review for edge cases) and learning (continuous prompt refinement).

### DE-2. Pipeline at Scale

This processes one document per Step Functions execution. Design a batch pipeline that handles 100,000 documents per day. What changes to the Step Functions architecture? Where would you parallelize, and where are the bottlenecks?

**Your answer:**

**Batch Pipeline Architecture (100K docs/day):**

**Current State Problem:** Sequential execution = 15s/doc × 100K = 1,500K seconds (~17 days). Unacceptable.

**Proposed Solution:**

1. **Ingestion Layer:** S3 Batch Operations or scheduled EventBridge rule triggers bulk load job every 5 minutes. Each load batches 500 documents into SQS queue.

2. **Parallelization Strategy:**
   - Use Step Functions Map state to fan-out: `Map[classify(doc1), classify(doc2), ..., classify(doc500)]` in parallel
   - Max parallelism = 500 concurrent Lambda invocations; AWS Lambda default concurrency = 1,000, so no bottleneck
   - Preprocess stage: stays sequential (reads S3 keys from SQS) but fast (<1s each)

3. **Bottleneck Analysis:**
   - **Bedrock rate limit:** 100 requests/second (AWS default). At 500 parallel Lambda calls, that's 500 req/s instantly. **BLOCKER.** Solution: purchase provisioned throughput (~$10K/month) or implement SQS queue with controlled fan-out (max 100 req/s).
   - **S3 throughput:** No issue; S3 auto-scales to 3,500 PUT/sec.
   - **Lambda cold starts:** Provision 500 concurrent Lambda containers to warm them; ~$5/day additional cost.

4. **Revised State Machine:**
   ```
   BulkLoad
      ↓
   Map[Preprocess(doc) → Classify(doc) → Extract(doc) → Aggregate(doc)]
      ↓
   WriteResults
   ```

5. **Expected Performance:**
   - Sequential: 1,500K seconds (~17 days) ❌
   - Parallel (batch=500, max concurrency=100 [rate-limited by Bedrock]): 15s × 200 batches = 50 minutes ✅

6. **Cost Impact:**
   - Additional: Provisioned throughput ($10K/month) or use on-demand with higher per-request cost
   - DynamoDB for aggregate results ($200/month vs. S3 JSON write latency)

### DE-3. Observability & Data Lineage

How would you monitor this pipeline in production? What metrics, alerts, and dashboards would you build? A downstream team also needs to know which model version and prompt version produced each extraction. How would you track that lineage?

**Your answer:**

**Monitoring Stack:**

1. **Key Metrics:**
   - Classification accuracy % per document type (compare predicted vs. actual in validation dataset)
   - Extraction confidence distribution (histogram: 0-25%, 25-50%, 50-75%, 75-100%)
   - Pipeline latency: p50, p95, p99 (target: p99 < 30s)
   - Cost per document (Bedrock tokens, Lambda duration)
   - Error rate by stage: preprocess, classify, extract, aggregate
   - Bedrock throttle errors (429 count, rate)

2. **Dashboards:**
   - **Operational (real-time):** Error rate, current throughput (docs/min), cost burn ($/hour), alert status
   - **Financial:** Cost/doc trend, monthly spend vs. budget, cost by customer
   - **Quality:** Accuracy by document type, confidence distribution, validation failure rate

3. **Alerts:**
   - Error rate > 1% → page on-call
   - p99 latency > 30s → investigate Bedrock
   - Cost/doc > 2x baseline ($0.01) → throttling detected
   - Bedrock throttles > 5% → request provisioned throughput

4. **Data Lineage Tracking:**

   Store metadata with each document result:
   ```json
   {
     "document_id": "doc-123",
     "processing_run_id": "2024-11-03_batch_001",
     "classification": {
       "model_version": "claude-haiku-5-5",
       "prompt_hash": "sha256_abc123...",
       "prompt_version": "v2.1",
       "bedrock_request_id": "req-uuid"
     },
     "extraction": {
       "model_version": "claude-haiku-5-5",
       "prompt_hash": "sha256_def456...",
       "prompt_version": "v1.0",
       "bedrock_request_id": "req-uuid2"
     },
     "timestamp": "2024-11-03T14:23:15Z"
   }
   ```

   Store in DynamoDB (partition key = document_id). Downstream teams query: "Which extraction generated field X?" → trace back to model version + prompt version, then retrieve prompt from S3.

5. **Audit Trail:**
   - Enable CloudTrail for all Bedrock API calls
   - Use Athena to query: "How many times did Haiku classify as drug_approval in November?"
   - S3 versioning for prompts: maintain history so you can reconstruct which prompt generated any result

### DE-4. Caching & Deduplication

If the same document is uploaded twice, the pipeline currently processes it again at full cost. How would you implement caching or deduplication? Consider where in the pipeline to check, what to use as a cache key, and the tradeoffs of different storage options (DynamoDB, S3 metadata, Elasticache).

**Your answer:**

**Caching Strategy:**

1. **Deduplication Check Point:** At preprocess stage, compute SHA256(document_content). Query cache before Bedrock calls.
   - If cache hit: return stored result → skip classify + extract calls (90% cost savings)
   - If cache miss: process normally, write result to cache for future hits

2. **Cache Key Design:**
   - Primary: `content_hash#{model_version}#{prompt_version}` (e.g., `sha256_abc123#haiku#v2.1`)
   - Ensures different model/prompt combos don't share results (allows A/B testing)
   - Example: Same document uploaded twice = same hash → cache hit (cost: $0); model updated = new hash → cache miss, reprocess

3. **Storage Option Analysis:**

   | Option | Lookup Speed | Cost | Best Use |
   |--------|-------------|------|----------|
   | **DynamoDB** | ~5-10ms | $1.25/1M requests | PRIMARY — recommended |
   | **Elasticache** | <1ms | $50-100/month + compute | Not worth overhead for this pipeline |
   | **S3 metadata** | 100-500ms (S3 Select) | $0.02/1M requests | Too slow |
   | **LocalLambda cache** | <1ms | Free | Only for single execution; lost between invokes |

4. **Recommended: DynamoDB Implementation:**
   ```python
   cache_key = f"{content_sha256}#{model_version}#{prompt_version}"
   cached = dynamodb.get_item(Key={"cache_key": cache_key})
   if cached and not cached.get("expired"):
       return cached["result"]  # Skip Bedrock calls
   else:
       result = bedrock_classify()  # Process normally
       dynamodb.put_item({
           "cache_key": cache_key,
           "result": result,
           "ttl": int(time.time()) + 2592000  # 30 days
       })
   ```

5. **Tradeoffs:**
   - **Pros:** 90% cost reduction if 30% of uploads are duplicates; huge savings for enterprise with repeat documents
   - **Cons:** Stale results if content changes; adds 5-10ms lookup latency; debugging harder (which extraction version?)
   - **Mitigation:** Document cache policy to users ("Results cached 30 days by content hash"); log cache hits in CloudWatch; versioned prompts prevent stale results across model updates

6. **Break-Even Analysis:**
   - 100K docs/day with 30% duplicates → 30K cache hits
   - Cost savings: 30K × $0.005/classification = $150/day = $4,500/month
   - DynamoDB cost: ~$37/month
   - Net savings: $4,463/month ✅ (massive ROI)

   Even with 10% duplicates (10K hits): $50/day savings = $1,500/month still justifies implementation.
