# Evaluation report

## Run recorded

Command:

```powershell
python -m app.eval.run --provider mock --prompts pathway_v1 pathway_v2 --output eval/results/baseline_mock.json
```

This run exercised the complete generation pipeline against 20 fixed learner profiles. The deterministic fixture provider supplied valid output, malformed JSON, invented topic IDs, and repeated schema-invalid output to cover first-pass success, repair, and fallback. These are pipeline robustness measurements; they do not estimate the quality of Qwen or another LLM.

| Provider / prompt | First schema valid | First semantic valid | Repair | Fallback | First hallucinations | Final valid | Final hallucinations | Budget compliant | Mean latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| mock-fixture / pathway_v1 | 70.0% | 60.0% | 20.0% | 20.0% | 10.0% | 100.0% | 0.0% | 100.0% | 2.525 ms |
| mock-fixture / pathway_v2 | 70.0% | 60.0% | 20.0% | 20.0% | 10.0% | 100.0% | 0.0% | 100.0% | 2.483 ms |

The machine-readable records, including each profile outcome and validation error, are in [`eval/results/baseline_mock.json`](../eval/results/baseline_mock.json). Latency is local fixture-pipeline latency and should not be compared with actual model inference.

## Findings and limitations

- **Before repair/fallback:** 70% of first outputs passed JSON/schema validation and 60% passed schema plus semantic validation. Two of twenty first outputs contained an invented topic ID (10%); no first output violated prerequisite order. The malformed and invented records were measured from the actual fixture run.
- **After repair/fallback:** all returned pathways passed semantic validation and budget checks (100%); no invented topic or URL reached a returned pathway. Four profiles needed repair and four used deterministic fallback.
- The injected malformed JSON and repeated invalid outputs were rejected. The repair loop recovered the single-repair cases, and the deterministic fallback handled cases that remained invalid.
- Prompt versions produced the same rates because the fixture provider intentionally returned the same scenario outputs for each version. This run does not establish that one prompt is better; the measured latency difference is fixture noise.
- A real local-model comparison was not run in this environment: it has Python 3.15 but no installed PyTorch or Transformers runtime, and no Hugging Face model weights. The default model can be evaluated on a supported Python environment with the local inference dependencies installed using `--provider local --models Qwen/Qwen2.5-1.5B-Instruct`.

## Next evaluation

Run the same profile set with a locally available model and save a separate result file. Review first-try semantic failures and update the prompt or validator only when the measured failure supports the change. Preserve this mock baseline for deterministic CI and regression checks.
