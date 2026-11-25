# Reference benchmark runner runbook

Issue #31 must not be closed using GitHub-hosted runners. The reference baseline
requires ten independent full-profile workflow runs on one stable Linux x64
self-hosted runner. Install the official GitHub Actions runner package on the
dedicated host first; do not run unrelated workloads on that host during the
benchmark.

## 1. Inspect and register the runner

Check existing runners:

    gh api repos/mojtaba-arvin/demand-forecast-kit/actions/runners \
      --jq '.runners[] | [.name, .status, ([.labels[].name] | join(","))] | @tsv'

If there is no dedicated runner with the required labels, request a one-time
registration token (valid for a limited time):

    export RUNNER_TOKEN="$(gh api --method POST \
      repos/mojtaba-arvin/demand-forecast-kit/actions/runners/registration-token \
      --jq .token)"

From the extracted official Linux x64 runner directory on the dedicated host:

    ./config.sh \
      --url https://github.com/mojtaba-arvin/demand-forecast-kit \
      --token "$RUNNER_TOKEN" \
      --labels demand-forecast-reference \
      --unattended \
      --replace
    ./run.sh

GitHub supplies the standard self-hosted, Linux, and X64 labels; the additional
label is demand-forecast-reference. Keep this runner online for the entire
benchmark batch. Do not paste the registration token into an issue or commit it.

## 2. Freeze the benchmark revision

After all intended code changes are merged, create an immutable tag pointing
to the exact main commit to be benchmarked:

    MAIN_SHA="$(gh api repos/mojtaba-arvin/demand-forecast-kit/commits/main --jq .sha)"
    gh api --method POST \
      repos/mojtaba-arvin/demand-forecast-kit/git/refs \
      -f ref=refs/tags/benchmark-reference-2026-11-25 \
      -f sha="$MAIN_SHA"

If that tag already exists, inspect its target; never move an existing
reference tag to a different commit. Use a new date/versioned tag instead.

## 3. Dispatch ten independent full-profile runs

Each loop iteration creates a separate workflow run. Five repeats inside one
workflow do not substitute for ten independent runs:

    for i in {1..10}; do
      gh workflow run performance-benchmarks.yml \
        --repo mojtaba-arvin/demand-forecast-kit \
        --ref benchmark-reference-2026-11-25 \
        -f profile=full \
        -f repeats=5 \
        -f runner_class=reference-self-hosted
    done

Inspect the ten runs and their uploaded artifacts:

    gh run list \
      --repo mojtaba-arvin/demand-forecast-kit \
      --workflow performance-benchmarks.yml \
      --limit 20

Confirm all ten runs used the same tagged SHA and the dedicated reference
runner. If any run used another runner class or a different SHA, it does not
count toward Issue #31. Record the hardware/OS/Python metadata and summarize
variance before proposing a regression threshold.

## 4. Closure criteria

Close Issue #31 only after all ten independent artifacts exist, their metadata
matches the frozen SHA and reference runner, and the resulting variance is
reviewed. Do not enable a performance regression gate until the measured
variance justifies a stable threshold.
