# Schema-drift audit: runtime writes vs schemas

**Goal:** Find places where runtime code writes fields that the schema disallows, or omits required fields, or has optional fields inconsistent across paths so validation could break.

**Scope:** item, qa_audit_report, run_record, compiled_plan / compile_metadata, dataset_spec, eval_result, oracle, failure_cluster, action_plan, data_card, agent_handoff, prompt_blueprint, eval_family, judge_spec, intent_spec. Provenance, duplicate_metadata, dedup fingerprint, blueprint/family/materializer fields.

---

## 1. Artifact-by-artifact summary table

| Artifact | Field | Where written | Schema status | Bug? |
|----------|--------|----------------|---------------|-----|
| **item** | item_id, dataset_spec_version, domain_tags, difficulty, task_type, prompt, input, input_schema, output_schema, constraints, provenance | a1_item_generator (all _make_*), materialize_target_to_item | required in item.schema.json; all set | No |
| **item** | provenance.created_at, created_by, source | a1_item_generator (every return dict) | required in provenance; all set | No |
| **item** | provenance.blueprint_id, family_id, materializer_type | a0_orchestrator (when blueprint present) | optional in provenance; allowed | No |
| **item** | version_bundle | a0_orchestrator | optional in item; allowed | No |
| **item** | judge_spec_id | a1_item_generator materialize_target_to_item | optional in item; allowed | No |
| **item** | constraints.no_subjective_judgement, safety_notes, locked_fields | a1_item_generator | required in constraints; all set | No |
| **qa_audit_report** | item_id, passed, stage, overall_failure_code, gates, patch_instructions, created_at | a4_qa_gate | required; all set | No |
| **qa_audit_report** | failure_code, explanation | a4_qa_gate | optional; set on all paths | No |
| **qa_audit_report** | duplicate_metadata | a4_qa_gate (when DUPLICATE_ITEM) | optional; structure matches schema | No |
| **qa_audit_report** | version_bundle | a0_orchestrator (after QA pass) | optional; allowed | No |
| **qa_audit_report** | gates[].gate, passed, failure_code, explanation | _gate_result() | required per gate; all set | No |
| **run_record** | run_id, dataset_name, dataset_spec_version, model_version, tool_snapshot_hash, seed, started_at, ended_at, paths, metrics | a0_orchestrator | required; all set | No |
| **run_record** | paths.run_dir, events_jsonl, artifacts_dir | a0_orchestrator | required in paths; all set | No |
| **run_record** | metrics.items_total, qa_passed, eval_passed, failures_total | a0_orchestrator | required in metrics; all set | No |
| **run_record** | metrics.attempted_total, qa_failed_total, item_abort_total, latency_ms_p50, latency_ms_p90 | a0_orchestrator | optional in metrics; allowed | No |
| **compiled_plan** | intent_spec, eval_families, prompt_blueprints, judge_specs, compiled_dataset_spec, compile_metadata | compiler.compile_to_plan | required; all set | No |
| **compile_metadata** | intent_spec_version, family_catalog_version, compiler_version, compiled_at | compiler | required; always set before merge | No |
| **compile_metadata** | warnings, planner_mode, raw_llm_*, planner_critic_report, etc. | compile_pipeline → compile_metadata_extra | optional in schema; all listed | No |
| **dataset_spec** | dataset_name, dataset_spec_version, allowed_domain_tags, capability_targets, defaults | compiler | required; all set | No |
| **capability_target** | target_id, domain_tags, difficulty, task_type, quota_weight | compiler | required; all set | No |
| **capability_target** | family_id, blueprint_id, materializer_config, min_count, etc. | compiler | optional in dataset_spec; allowed | No |
| **eval_result** | item_id, verdict, score, error_type, evidence, raw_output_ref, model_version, seed, created_at | a2_verifier _result/_finalize_fail | required; all set | No |
| **eval_result** | raw_output_ref (sha256, uri, mime, bytes only) | a2_verifier builds 4-key ref; a0 HTTP path strips to 4 keys | additionalProperties: false; only 4 keys used | No |
| **eval_result** | evidence[].kind | a2_verifier (all evidence entries) | required in evidence items; set | No |
| **eval_result** | version_bundle, task_type, eval_method, verification_ladder | a2_verifier, a0_orchestrator | optional; allowed | No |
| **oracle** | item_id, eval_method, expected, method_justification, evidence_requirements, leak_check, created_at | a1b_oracle_builder | required; all set | No |
| **oracle** | leak_check.passed, notes | a1b_oracle_builder | required in leak_check; set | No |
| **failure_cluster** | cluster_id, error_type, item_ids, count, hypothesis, owner, recommended_actions | a3_diagnoser | required; all set | No |
| **action_plan** | cluster_id, summary, root_cause_hypothesis, recommended_owner, priority, estimated_blast_radius, top_examples, next_action | a3_diagnoser | required; all set | No |
| **action_plan** | top_examples[].item_id | a3_diagnoser | required in items; set | No |
| **data_card** | dataset_name, dataset_spec_version, motivation, intended_use, composition, limitations, version_history | a5_packager | required; all set | No |
| **agent_handoff** | run_id, item_id, agent_id, stage, status, created_at, output_ref, version_bundle | handoffs.emit_handoff | required; all set | No |
| **prompt_blueprint** | blueprint_id, family_id, blueprint_type, materializer_config, etc. | prompt_program_compiler | validated before write | No |
| **eval_family** | family_id, family_label, objective, observable_targets, slot_weight | intent_planner, LLM output normalized to catalog | required; enforced by catalog/normalize | No |
| **version_bundle** | dataset_spec_version, rubric_schema_version, eval_script_version, model_version, tool_snapshot_hash, seed | versioning.build_version_bundle | required in version_bundle; set | No |

---

## 2. Cross-cutting checks

- **Provenance:** item.schema.json `provenance` has `additionalProperties: false` and allows only: created_at, created_by, source, source_refs, asset_refs, tool_calls, blueprint_id, family_id, materializer_type. Runtime only sets those (generators set created_at/created_by/source; orchestrator adds blueprint_id, family_id, materializer_type when blueprint present). **No drift.**

- **Duplicate metadata:** qa_audit_report.duplicate_metadata has properties (family_id, blueprint_id, materializer_type, task_type, dedup_fingerprint, fingerprint_inputs, normalized_prompt_skeleton_preview, duplicate_match). a4_qa_gate sets the same. duplicate_match has same_prompt_skeleton, same_family, same_blueprint, same_materializer. **No drift.**

- **Dedup fingerprint:** compute_dedup_fingerprint returns (hash_str, inputs). Fingerprint inputs are used only for dedup logic and duplicate_metadata.fingerprint_inputs; not written into item schema. **No drift.**

- **Blueprint/family/materializer:** Written in capability_targets (dataset_spec), eval_families, prompt_blueprints, and item.provenance. All corresponding schemas allow these. **No drift.**

- **raw_output_ref:** eval_result.raw_output_ref has `additionalProperties: false` and required sha256, uri, mime, bytes. save_artifact_text() returns also `created_at`; the orchestrator HTTP-failure path (a0_orchestrator line 298) and a2_verifier (line 271–276) both build a 4-key ref for eval_result. **No drift.**

---

## 3. Optional-field consistency (paths that could break validation)

- **Item without blueprint:** When no blueprint is passed, item still has provenance with only created_at, created_by, source (from generator). Provenance schema allows optional blueprint_id, family_id, materializer_type. **Safe.**

- **QA report (pass vs fail):** Pass path sets failure_code="", explanation="PASS"; fail paths set overall_failure_code and failure_code. Both paths include required gates, patch_instructions, created_at. **Safe.**

- **run_record when no HTTP:** metrics omit latency_ms_p50, latency_ms_p90 (optional). **Safe.**

- **compile_metadata_extra:** Merge is `{**compile_metadata, **compile_metadata_extra}`. Required keys are always in first dict; extra only adds optionals. **Safe.**

---

## 4. Schemas with no runtime validation (informational)

- **run_summary.json:** No schema file; not validated. Package_run writes it; consumers may rely on its shape. Consider adding run_summary.schema.json if you want it contract-bound.

- **batch_plan.json:** No schema; internal artifact. **OK to leave as-is.**

---

## 5. Exact files/lines relevant to schema compliance

(No bugs found; these are the main write sites that were audited.)

| Artifact | Primary write / validate sites |
|----------|--------------------------------|
| item | eval_engine/agents/a1_item_generator.py (all _make_* returns); a0_orchestrator.py (provenance enrich L161–164, version_bundle L168); a5_packager.py L27 validate |
| qa_audit_report | eval_engine/agents/a4_qa_gate.py (_gate_result L65–66, report dicts L315–366, L372–382, duplicate_metadata L365); a0_orchestrator.py L204 validate, L249 version_bundle |
| run_record | eval_engine/agents/a0_orchestrator.py L468–494, L495 validate |
| compiled_plan / compile_metadata | eval_engine/agents/compiler.py L138–157, L160 validate; compile_pipeline merge L148–149 |
| dataset_spec / capability_targets | eval_engine/agents/compiler.py L127–135, L136 validate |
| eval_result | eval_engine/agents/a2_verifier.py (_result L54–71, raw_ref 4-key L271–276); a0_orchestrator.py L291–302 (HTTP fail, 4-key raw_output_ref L298), L355 validate |
| oracle | eval_engine/agents/a1b_oracle_builder.py; a0_orchestrator.py L187 version_bundle; a5_packager.py L29 validate |
| failure_cluster / action_plan | eval_engine/agents/a3_diagnoser.py L202–225, L229–242; a5_packager.py L33–35 validate |
| data_card | eval_engine/agents/a5_packager.py L113–121, L122 validate |
| agent_handoff | eval_engine/core/handoffs.py L21–34, L35 validate |

---

## 6. Tests run

- tests/test_contracts.py (including run_record and diagnoser schema validation)
- tests/test_item_schema.py
- tests/test_hard_intent_e2e_contract.py (item, oracle, eval_result validate)
- tests/test_compile_layer.py (compiled_plan, dataset_spec)
- tests/test_hard_intent.py (intent_spec, dataset_spec)

**Result:** All 57 tests passed.

---

## 7. Verdict

- **Mismatches found:** None. No case where code writes a field disallowed by the schema, or omits a required field, or uses an optional field in a way that breaks validation across paths.
- **Patches required:** None.
- **Safe to push as-is:** **Yes.** Schema-drift audit shows no bugs; runtime writes align with the listed schemas, and the relevant test suite passes.
