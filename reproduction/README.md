# When Correct Answers Carry Invalid State

This artifact replays the explicit-state carrier experiment from saved model answers. The preprint by Jiangwei Xue, Zhida Qin and Yuda Bi is identified by DOI [10.5281/zenodo.22720976](https://doi.org/10.5281/zenodo.22720976). Its PDF is supplied separately. LATEST_PAPER.json identifies the PDF and corresponding TeX source.

## Reproduce the reported results

Install Python 3.10 or later. The analysis uses the standard library and runs offline. Extract the ZIP, enter its top-level directory, and replace the placeholder below with the path to the downloaded ZIP.

<!-- RELEASE_COMMAND:verify -->
```sh
python3 tools/verify_package.py --archive <ARCHIVE_PATH>
```
<!-- END_RELEASE_COMMAND:verify -->

The command reads the archive, checks member identities and executes the deterministic analysis on a fresh extraction. The scientific report contains `"passed": true` and `"api_calls_performed": 0` when all comparisons succeed. To save the results, run the paper's analysis entry point from the extracted directory and give it an output path outside that directory.

```bash
python3 scripts/reproduce_public_release.py --archive <ARCHIVE_PATH> --output ../results.json
```

Its optional `--rows-output` argument writes a new JSON Lines file containing native-to-canonical state parses, full V2/V3 scores, primary executor records and row-level evidence hashes. Allow sufficient disk space for expanded rows.

## Recorded model responses and experiment scaffolding

The response files separate state-update calls, hosted final calls and local final-answer construction. The deterministic controls are generated locally. Use the keys in `inputs/` to select an episode. Inspect any available messages and attempt outcomes with:

```sh
python3 -m scaffold.replay_calls --tier primary --row-id 'pcgds_v2_00001_api_migration_state_transition_easy::qwen37max::loop_only::budget1200::run1'
```

To check the request/body, parsing and state-compiler connections across all populations:

```sh
python3 -m scaffold.replay_calls
python3 -m scaffold.test_replay
```

The response dictionary contains exact UTF-8 text addressed by SHA-256. A recovered update is accepted only when its text reproduces the compiler's frozen pre-compilation SHA-256. This also permits matching a retained occurrence of identical text across observations. `digest_only` marks an unavailable update; `empty_extracted_content` marks a known empty extraction. The latter can follow a transport failure. Neither convention infers an unobserved reply or creates a completion. For final hosted calls, attempt indices and HTTP status are included where recorded, with model message content recovered from the retained choice. Transport failures can have no response body.

| Population | Update stages | Exact nonempty update texts | Empty extracted updates | Updates with digest only | Hosted final calls with text / planned | Locally constructed final answers |
|---|---:|---:|---:|---:|---:|---:|
| Primary | 37800 | 3892 | 10 | 33898 | 5997 / 6000 | 1200 |
| Qwen supplement | 7560 | 836 | 0 | 6724 | 1200 / 1200 | 240 |
| Five-model budget 300 | 4200 | 188 | 0 | 4012 | 600 / 600 | 200 |
| Qwen budget 300 | 840 | 22 | 0 | 818 | 120 / 120 | 40 |
| One-shot sanity | 0 | 0 | 0 | 0 | 40 / 40 | 0 |
| Historical pilot | 3454 | 382 | 2 | 3070 | 532 / 532 | 118 |

The historical pilot includes the core pilot, its two targeted replacements, and static sanity; row populations and historical links retain separate denominators. Across these pilot updates, attempt counts and retry-level responses were not retained. The primary, supplementary and budget cohorts record per-update attempt counts and status sequences. Their update response envelopes are generally recorded only by digest. Content verification proves the text consumed by the original compiler, not the entire HTTP response or retry history. The one-shot baseline retains all final-call contents and attempt status.

`scaffold/experiment.py` implements episode order: construct the prompt from the next visible segment and permitted prior state, construct the provider request, consume returned text, compile and fit the carrier to the frozen budget, then emit the provider or deterministic final answer for that method. `run_episode` accepts a transport callback. `retry_transport` accepts an attempt function and sleeper for the main-matrix conditions. The payload parameters and retry values used in the replay are in `scaffold/conditions.json`. The one-shot parser, legacy pilot prompt/compiler variants, main-matrix slot compiler and provider message extractor accompany the V1/V2/V3 scoring code and independent executor. Full-row comparisons cover the independent V2 reference scorer, production scorer and V2 executor, alongside the V3 evaluator and executor. The archived V2 representation failure is an expected control result. The original V2 metamorphic and mutation cases run as part of ZIP verification. Only rows with complete stage text, plus known empty extractions, support end-to-end replay of the original episode; other rows support scoring the saved final output and independently checking each recoverable stage. Running fresh traffic would require an available endpoint and valid access, and historical model generations need not recur.

## Evidence and interpretation

- **Design and model inputs (Tables 1–6, 13 and Figure 1).** The manuscript supplies the comparisons to prior work and the worked field-semantics example. `inputs/tasks.jsonl` contains the ordered visible segments, answer instructions and evaluator-only oracle for the forty tasks. `scoring/protocol.py` supplies the state-update and final-answer prompt constructors, deterministic state compiler and request construction. The scorer-only oracle is never input to these constructors. Model conditions, routing and generation settings appear in `inputs/requests.json` and the per-tier request keys. Budget values 300, 600 and 1,200 are carried-state characters.
- **Primary outcomes (Tables 7–12, 14–16 and Figures 2–4).** The primary population contains 7,200 rows across 40 tasks, five model conditions, six protocols, two budgets and three runs. Saved rows contain the final model output and the bounded native carrier. The per-segment hard-cap flag identifies an actual truncation. The V2 dedicated-answer scorer, V3 state adapter and independent executor consume their respective surfaces. The executor reads the carrier and task contract. Conditional executor differences use the within-method task-cluster bootstrap.
- **Legacy analyses (Tables 17–27 and Figure 5).** Legacy V1 and revised V2/V3 definitions are scored separately. The analysis includes 1,440 Qwen supplement rows, 800 five-model budget-300 rows, 160 Qwen budget-300 rows, 40 one-shot sanity rows and 36,000 deterministic controls. The control outputs and states are regenerated from the five local policy functions, then compared with saved output/state digests. The one-shot sanity prompt is reconstructed by `scoring/sanity.py`. The oracle ceiling uses evaluator-only information within the control tier. The bootstrap uses 10,000 task-cluster draws with the original seeds. The reporting comparison checks 523 displayed numeric values from 21 tables, including supplementary sensitivities and interval bounds.
- **Saved answers and references.** `inputs/*_requests.jsonl` contains frozen logical requests linked to response rows by their scientific keys. `final_output` and `final_state` preserve the saved scorer inputs. `provider_choices` retains the final-call model content and finish reason where present. `calls` contains the available per-update hash receipts. Some state-update calls were retained only as summaries; regenerating a missing hosted response is outside the offline replay scope. The scientific reference rows in `reference/` hold the frozen outcomes for each tier. The public row digest binds task, request, saved score input, parsed state, scores and executor.
- **Historical H5/E5 evidence.** The 644 core pilot records, two targeted replacements and four static-sanity records in `inputs/historical.jsonl` are a separate provenance series. Two core gaps and their later replacements remain distinct. The historical manifest-entry and linked H5 digests recompute from the recorded fields. The saved final answer and carrier reproduce the original parsed-output digest, and deterministic rescoring reproduces the original full metric-record digest for all 650 rows. Separately, the distributed record digest binds the provided response projection, scientific outcome and original identities. The original complete transport envelopes and original outer lock preimages are held separately, so these two historical byte hashes remain commitments. The pilot scorer is rerun on each provided output and state. The current experiment tiers retain their own denominators.
- **Limitations.** Reported associations describe these tasks, protocols and recorded model conditions. Offline replay does not establish independent external reproduction or repeat nondeterministic provider calls.

The code and original derived materials are governed by LICENSE.md and the texts under LICENSES.
