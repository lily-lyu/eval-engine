gate:
	python3 -m eval_engine.cli gate \
	  --break_suite examples/break_suite.jsonl \
	  --golden_suite examples/golden_suite.jsonl \
	  --sut_url http://127.0.0.1:8000/run \
	  --sut_timeout 30 \
	  --min_pass_rate 0.95 \
	  --artifacts_dir ci_artifacts/gate
