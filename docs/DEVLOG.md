# Development Log

Real problems, in the order they occurred: what happened, root cause, fix.

## Lambda concurrency quota at 10

- What happened: the preflight check showed an account limit of 10 concurrent Lambda executions in us-east-1.
- Root cause: the default limit on this account is low. The design runs two MSK consumer groups plus the lifecycle and WebSocket handlers, all sharing that pool.
- Fix: an increase to 1000 was requested through Service Quotas at the start of the build, status PENDING. If it is not granted before the billable session, the design is adapted to fit in 10 concurrent executions (larger batches per invocation, capped concurrency per function). The outcome is recorded here and in the README.

## No Python virtual environment on the workstation

- What happened: `python3 -m venv` failed because `ensurepip` is missing (the `python3.14-venv` system package is not installed, and installing it needs administrator rights).
- Root cause: Ubuntu ships venv support as a separate package.
- Fix: all Python work (tests, local harness, simulator, measurements, history generator) runs in a `python:3.13-slim` based image built from `local/dev.Dockerfile`. This also aligns the test interpreter with the Lambda runtime instead of the workstation's 3.14.

## Quoting error in the OSRM measurement script

- What happened: the first run of `scripts/measure_osrm_local.sh` measured startup and memory correctly but crashed on the last line with a Python `SyntaxError`.
- Root cause: escaped double quotes inside an f-string passed through `python3 -c` in single quotes.
- Fix: the sample route is printed with `jq` instead. The script was rerun in full and only the clean run is kept in `proof/01-osrm-local-memory-startup.txt`. Startup was 1.38 s on the first run (cold file cache) and 0.87 s on the rerun; both are reported.

## First ride after a harness restart found no driver

- What happened: right after restarting the local harness, a ride request returned `RideNoDriver` with zero available drivers. The same request a few seconds later matched.
- Root cause: the harness clears Redis on start, and the matching consumer group had not yet rejoined and applied a positions batch, so the driver index was empty. ElastiCache behaves the same way after creation: the index only fills once the first batch is consumed.
- Fix: demo scripts wait for a positions snapshot that contains drivers before sending the first request.

## Two different ETA values for the same ride

- What happened: the first full local trace showed `eta_s=239` on `RideMatched` and `eta_s=80` on `DriverEnRoute`.
- Root cause: matching reports the real OSRM road time, while the simulator reported wall-clock time under its 3x time compression, under the same field name.
- Fix: the simulator field is renamed `sim_eta_s`; the UI shows the road ETA from matching.

## Surge shown in almost every zone

- What happened: the first automated UI capture showed a surge label (x1.25 or x1.5) on nearly every hexagon of the Live Ops Map at idle.
- Root cause: 20 drivers spread over 18 H3 resolution 7 zones is about one driver per zone, while the pricing rule required two available drivers per zone before surge stayed at 1.0. Most zones were "short" by construction, so a supply drop in one zone would not stand out.
- Fix: the wandering area was narrowed to central Nairobi (7 zones, about 3 drivers each) and the baseline supply lowered to one driver per zone. Surge now appears only when a zone has no available driver or demand exceeds supply. Every local measurement and capture taken before this change was re-run.

## Recording script wrote to a missing directory

- What happened: the first two runs of `scripts/record_feed.py` followed a full ride but crashed when saving, so no replay file existed.
- Root cause: `ui/public/` did not exist yet and the script did not create it.
- Fix: the script creates the parent directory before writing.

## Pre-push hook false positive on Python decorators

- What happened: the hook blocked the Phase 2 push, reporting `@pytest.fixture` lines as e-mail addresses.
- Root cause: in the patch text these lines start with `+`, which the e-mail pattern accepted as a local part (`+@pytest.fixture`).
- Fix: the local part must now start with a letter or digit. The failing cases (ARN with account ID, access key, foreign e-mail, wrong author, assistant attribution) were re-tested and are still blocked.

## Stopping the dev servers killed the stopping command

- What happened: `pkill -f "vite --port 5173"` also terminated the shell running it, so the commands after it did not run.
- Root cause: `pkill -f` matches full command lines, including the one that contained the pattern.
- Fix: dev servers are stopped by PID taken from the listening port.

## OSRM pod crashed on EKS: graph file missing from the image

- What happened: the OSRM pod on EKS restarted in a loop. The first error was `Permission denied` on the graph files; after a permissions change it became `File "/data/nairobi.osrm.fileIndex" mapping failed: ... Invalid argument`.
- Root cause, found in three steps: (1) the image runs as an unprivileged user (65534) and the files were owner-only; (2) the first fix, `COPY --chmod=0444`, also removed the execute bit from the `/data` directory, so it could not be traversed; (3) the real cause of the mapping error: `nairobi.osrm.fileIndex` on the build host was owned by root with mode 700 (written by the preprocessing container), the build user could not read it, and the image build context included it as an empty file without any error. An empty file cannot be memory-mapped. The local stack never saw this because it mounted the files into a container running as root.
- Fix: the graph files are made world-readable at the end of `services/osrm/prepare.sh`, the Dockerfile uses `COPY --chmod=0755`, and the image was verified locally (route answered while running as uid 65534) before a new tag was pushed. The arm64 check under qemu was not usable for this: OSRM's memory mapping also fails under emulation, so the check ran on an amd64 build of the same Dockerfile.
