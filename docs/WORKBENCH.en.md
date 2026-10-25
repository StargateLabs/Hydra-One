# Performance and Benchmark — the mod’s engineering workbench

## From a change to repeatable evidence

Performance and Benchmark are the workbench for observing models and evaluating the mod’s enhancements. Performance organizes measurements; Benchmark configures and executes tests against the selected backend. Their purpose is to bind a result to its model, runtime, protocol and configuration, rather than publish an unqualified leaderboard. Cache, context, thread and backend changes must be compared through consistent experiments.

## Performance: inspect recorded behavior

The workspace includes a measurement archive, model/session selectors, name/runtime search, a HYDRA One filter, pagination and CSV export of filtered results. Component versions have a dedicated strip. Counters distinguish loaded reports, completed runs and other outcomes. Failed outcomes remain visible. Host telemetry and request metrics describe different things and must not be merged into a single performance claim.

## Benchmark: run an explicit protocol

The connected-backend benchmark requires a ready engine and acquires the conversation reservation. It accepts 3–10, 20 or 30 measured runs after one warmup, with an output budget of 32–1,024 tokens. The record includes prompt hash, generation settings, streaming, context and runtime metadata. Every sample retains actual output tokens and whether the budget was reached. Cancellation stops the job; partial samples do not establish a completed protocol.

## Metric boundaries remain explicit

HTTP wall time covers the request through response completion; wall throughput is output tokens divided by that time. Streaming TTFT measures the first nonempty content event. Decode and prefill are reported only when the backend exposes them, never invented from total latency. Comparison accepts 2–8 distinct reports and checks samples, warmups and protocol. Local checkpoint content can be fingerprinted rather than identified by a model alias alone.

## Quality is a separate check

The optional response check uses 12 closed-reference tasks and a dataset identity. It is a bounded check, not a general intelligence evaluation or a substitute for domain testing. Fast but unusable output is not a successful test. Incomplete or out-of-contract samples must not become new performance records.

## HYDRA experiments and enhancements

The persistent laboratory distinguishes imported evidence from newly executed runs. Records bind model/runtime identity, profile, samples, events, artifacts and process cleanup. Feature controls expose dependencies and gates before execution. Caches, checkpoints, retrieval, scoring, scheduling and I/O have specific execution paths. A software contract or historical test does not qualify a GPU path, another model or an unmeasured speedup.

## Evaluate changes deliberately

Choose and identify a model, fix the protocol, record a baseline, change an identifiable parameter or path, repeat the run and compare metrics with the same scope. Inspect output, errors, memory and process cleanup before retaining the report. This documents implemented tools, not a claim that every enhancement has completed end-to-end qualification.

## Implementation / Implementazione

- [serve/optional_benchmark.py](../serve/optional_benchmark.py)
- [serve/optional_reports.py](../serve/optional_reports.py)
- [serve/benchmark_comparison.py](../serve/benchmark_comparison.py)
- [serve/lab_metrics.py](../serve/lab_metrics.py)
- [serve/quality_suite.py](../serve/quality_suite.py)
- [serve/hydra_lab_benchmarks.py](../serve/hydra_lab_benchmarks.py)
- [serve/hydra_feature_control.py](../serve/hydra_feature_control.py)
- [serve/web/performance-workspace.js](../serve/web/performance-workspace.js)

[Platform / Piattaforma](PLATFORM.en.md) · [Source inventory / Inventario](MODULES.md)
