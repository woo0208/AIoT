# E0-P2 synthetic instrumentation overhead

SYNTHETIC_STRUCTURAL_TEST_ONLY. No camera, footage, training, real MediaPipe/Depth inference or E1 optimization.
Fixed cached geometry/metadata + original H9 aggregation + prediction stub; accelerated input, not real 15FPS.
Identical deterministic CPU load: sum(k*k for k in range(8192)) per observation; synthetic compute only.
3 fresh processes per mode, 20 segments x 151 observations per process. Order rotates.
External frame timer and CPU/RAM observer are identical for OFF/summary/detailed. No warmup exclusion.
Table: median of per-process metrics; p95 is not a pooled or sensor-to-decision p95.

|mode|frame p95 ms|throughput frames/s|process CPU p50 % (one core=100)|system CPU p50 %|RSS observed peak MiB|Private observed peak MiB|shutdown publication ms|observer bytes|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|off|0.3003|3855.4399|35.5516|2.8914|126.0742|1579.3789|0.0310|0.0000|
|summary|0.3644|3340.6470|39.6323|3.2663|127.9609|1581.9609|3.6448|24560.0000|
|detailed|0.3644|3260.7479|38.4907|2.9572|154.0273|1608.2422|118.0407|12311961.0000|

All input hashes and functional result hashes agree across modes and repetitions.
Numeric detailed records buffer in RAM, then serialize on shutdown; no hot-loop file I/O, frame skip, queue or backend change.
OFF keeps the same FS3 lifecycle/validation, with timing/metadata/resources/export disabled. Shared harness still has overhead.
CPU deltas and RAM are observed process resources; short runs, OS scheduling, background system load and timer granularity limit interpretation.
Sampled RAM peaks can miss transients; Private is not resident RAM. OS peak is process-lifetime cumulative, hence fresh worker isolation.
Resource boundary samples include observer start/stop. Loop throughput excludes observer join and file publication, reported separately.
GPU inventory/utilization is device-wide when supported. Actual MediaPipe backend, process GPU attribution, SDK queue/drop count and sensor missing rate remain NOT_MEASURED.
This measures synthetic observer cost only; it is not deployed FS3 latency/FPS, a D455 result or evidence of classification improvement.
Evidence: local_private/results.json. No raw images/features/identities or trained models exported. No commit/push.

## Historical scope note — 2026-11-10

The table and original narrative above describe the pre-P3 implementation measured on 2026-11-09. P3 subsequently introduced bounded checkpoints and processing-loop file I/O. The current benchmark tool now describes that storage behavior, but this historical table has not been rerun or relabeled as current E0/E1 overhead. Current-source hash checks are expected to reject historical evidence with different source hashes. Original numeric evidence remains local-only; the values above are preserved unchanged.
