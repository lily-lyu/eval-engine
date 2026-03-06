#Case Study: Structured Extraction Failure Detection and Remediation

## Overview

This demo shows how the evaluation engine handles a **structured-extraction failure** with using typed evidence, evidence-specific diagnosis, and actionable data requests.

In this case, the break suite injects a wrong field value: the model output has the correct schema (name, email, company) but the **email** value is wrong (`wrong@example.com` instead of `alice@example.com`).

The engine detected the failure, classified it as `STRUCTURED_FIELD_VALUE_MISMATCH`, produced a root-cause hypothesis and next action, and generated a data request specialized for that evidence code.

---

## Scenario

**Task type:** `json_extract_structured`  
**Injected failure:** one required field has the wrong value  

**Input text:** `Name: Alice; Email: alice@example.com; Company: Acme`

**Expected extraction (oracle):**

| Field   | Expected value        |
| ------- | --------------------- |
| name    | Alice                 |
| email   | alice@example.com     |
| company | Acme                  |

**Injected behavior:** model output matched schema but used the wrong value for `email`:

```json
{"name": "Alice", "email": "wrong@example.com", "company": "Acme"}
```

### Before / After Summary

| Phase        | Verdict | Error Type               | Evidence Code                 | Evaluation Status |
| ------------ | ------- | ------------------------ | ----------------------------- | ----------- |
| Wrong value  | fail    | PROGRAMMATIC_CHECK_FAILED | STRUCTURED_FIELD_VALUE_MISMATCH | fail        |
| Correct value| pass    | none                      | none                          | pass        |

---

## Failure Detection

When the injected output was evaluated, the engine produced:

- **Item ID:** `break_structured_fail`
- **Task Type:** `json_extract_structured`
- **Verdict:** fail
- **Error Type:** PROGRAMMATIC_CHECK_FAILED
- **Evidence Code:** STRUCTURED_FIELD_VALUE_MISMATCH

The verifier also emits **richer evidence** so downstream tooling can act on it:

- **Dimension:** `structured_extraction`
- **Expected:** `alice@example.com`
- **Observed:** `wrong@example.com`
- **Locator:** `{"field": "email"}`

This is important because the engine did not stop at "programmatic check failed." It identified the specific failure mode and the exact field and values, so diagnosis and data requests can be tailored.

---

## Diagnosis

The diagnoser grouped the failure into the following cluster:

- **Cluster ID:** `PROGRAMMATIC_CHECK_FAILED/STRUCTURED_FIELD_VALUE_MISMATCH|json_extract_structured|programmatic_check`

It then produced a structured root-cause analysis (specific to `json_extract_structured` + `STRUCTURED_FIELD_VALUE_MISMATCH`):

- **Root cause hypothesis:** Extractor is brittle to layout variation or distractor spans; field value chosen incorrectly.
- **Recommended owner:** data
- **Priority:** 1
- **Next action:** Add extraction supervision for paraphrased layouts, reordered fields, and distractor-heavy examples.

Other evidence codes for the same task type get different hypotheses and actions (e.g. `STRUCTURED_FIELD_MISSING` → full-slot coverage; `STRUCTURED_EXTRA_FIELD_PRESENT` → schema-obedience).

---

## Closed-Loop Action

A6 converted the failure into a structured remediation request, **specialized by evidence code**:

- **Issue type:** STRUCTURED_FIELD_EXTRACTION_BAD
- **Owner type:** data
- **What to collect:** Collect distractor-heavy value selection examples; paraphrased layouts, reordered fields, and distractor spans.
- **Template hint:** Vary field order, separators, and distractor spans; grade correct field value under noise.
- **Verification eval:** Programmatic structured extraction failure rate drops.

For `STRUCTURED_FIELD_MISSING` or `STRUCTURED_EXTRA_FIELD_PRESENT`, the same issue type would be used but with different what_to_collect and template_hint text.

---

## Recovery

Recovery is demonstrated by comparing failing and corrected outputs under the same checker:

- the wrong-value output is correctly rejected
- the corrected output is correctly accepted
- the same programmatic check therefore distinguishes bad extraction behavior from correct extraction behavior

Recovery is measured through the same evaluation and release mechanism used to detect the failure.

---

## What This Demonstrates

This case shows that the engine can:

- detect structured-extraction failures with **typed evidence codes** (e.g. STRUCTURED_FIELD_VALUE_MISMATCH, STRUCTURED_FIELD_MISSING, STRUCTURED_EXTRA_FIELD_PRESENT)
- attach **rich evidence** (dimension, expected, observed, locator) for tooling and debugging
- produce **evidence-specific diagnosis** (root-cause hypothesis and next action per evidence code for `json_extract_structured`)
- generate **evidence-specific data requests** (what_to_collect and template_hint tailored to the failure mode)

In other words, the system turns a single "programmatic check failed" into a precise failure category, a credible hypothesis, and a concrete backlog ask.

---

## Why This Matters

Structured extraction is common (forms, entities, key-value pairs). Failures are only useful if they lead to:

- a precise failure category (value mismatch vs missing field vs extra field)
- a credible root-cause hypothesis (e.g. layout/distractor brittleness vs slot omission)
- a concrete next action (e.g. distractor-heavy examples vs full-slot coverage)
- a measurable recovery path (same programmatic check passes after data/model changes)

This demo shows that the engine supports that full loop for structured extraction.
