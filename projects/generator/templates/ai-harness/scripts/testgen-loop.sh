#!/usr/bin/env bash
# TestGen loop — generate test cases from docs for all slices
# Usage: testgen-loop.sh [maxIterations]
# When parallelism.workers > 1, acts as orchestrator spawning testgen-worker.sh processes.
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

require_harness_deps
cd "$REPO_ROOT"

max="${1:-$(jq -r '.loop.maxIterations // 30' "$TESTGEN_CONFIG")}"
workers="$(get_testgen_workers)"

if [[ "$workers" -le 1 ]]; then
  iter=0

  aih_section "TestGen loop (max=${max})" loop
  print_harness_env

  while [[ "$iter" -lt "$max" ]]; do
    if all_test_cases_current; then
      echo "TESTGEN_COMPLETE"
      exit 0
    fi

    iter=$((iter + 1))
    aih_section "TestGen iteration ${iter}/${max}" iteration

    tag="$(pick_next_testgen_requirement_tag)"
    if [[ -z "$tag" ]]; then
      echo "TESTGEN_COMPLETE"
      exit 0
    fi

    set +e
    run_testgen_tag_until_current "$tag" 1
    status=$?
    set -e

    if [[ "$status" -ne 0 ]]; then
      aih_warn "TestGen iteration ${iter} did not pass; continuing with fresh context"
    fi

    if all_test_cases_current; then
      echo "TESTGEN_COMPLETE"
      exit 0
    fi
  done

  aih_err "Max TestGen iterations (${max}) reached"
  read -r pending remaining < <(count_pending_requirement_tags)
  aih_info "Remaining requirement tags without test cases: ${pending} / ${remaining}"
  exit 1
fi

# --- Orchestrator mode (workers > 1) ---
RID="$(run_id)"
ensure_runs_dir
combined_log="${RUNS_DIR}/${RID}-testgen-orchestrator.log"
: > "$combined_log"

aih_section "TestGen orchestrator (workers=${workers}, maxWaves=${max})" loop
print_harness_env
aih_info "Combined log: ${combined_log}"

export AIH_RUN_ID="$RID"

wave=0
script_dir="$(cd "$(dirname "$0")" && pwd)"

while [[ "$wave" -lt "$max" ]]; do
  if all_test_cases_current; then
    echo "TESTGEN_COMPLETE"
    exit 0
  fi

  wave=$((wave + 1))
  aih_section "TestGen wave ${wave}/${max} (${workers} workers)" iteration

  pending_tags=()
  tag=""
  while IFS= read -r tag; do
    [[ -z "$tag" ]] && continue
    pending_tags+=("$tag")
  done < <(list_pending_requirement_tags)

  if [[ "${#pending_tags[@]}" -eq 0 ]]; then
    echo "TESTGEN_COMPLETE"
    exit 0
  fi

  aih_info "Pending tags this wave: ${#pending_tags[@]}"

  assign_testgen_worker_tag_files "$RID" "$workers" "${pending_tags[@]}" >/dev/null

  worker_pids=()
  worker_tag_counts=()
  w=0
  tags_file=""
  raw_log=""
  tag_count=0

  for ((w=1; w<=workers; w++)); do
    tags_file="$(testgen_worker_tags_file "$RID" "$w")"
    [[ -f "$tags_file" ]] || continue

    tag_count=0
    while IFS= read -r tag || [[ -n "$tag" ]]; do
      [[ -z "$tag" ]] && continue
      tag_count=$((tag_count + 1))
    done < "$tags_file"

    if [[ "$tag_count" -eq 0 ]]; then
      continue
    fi

    raw_log="${RUNS_DIR}/${RID}-testgen-worker-${w}.log"
    if [[ "$wave" -eq 1 ]]; then
      : > "$raw_log"
    else
      printf '\n==> TestGen wave %s/%s (worker %s)\n' "$wave" "$max" "$w" >> "$raw_log"
    fi

    aih_info "Spawning worker ${w} (${tag_count} tags) → ${raw_log}"

    (
      export AIH_RUN_ID="$RID"
      export AIH_TESTGEN_WORKER_ID="$w"
      "${script_dir}/testgen-worker.sh" "$w" "$tags_file" 2>&1 \
        | tee -a "$raw_log" \
        | prefix_testgen_worker_output "$w" \
        | tee -a "$combined_log"
    ) &
    worker_pids+=("$!")
    worker_tag_counts+=("$tag_count")
  done

  wave_failed=0
  pid=""
  worker_idx=0
  worker_timeout_ms=0
  for pid in "${worker_pids[@]}"; do
    worker_timeout_ms="$(get_testgen_worker_timeout_ms "${worker_tag_counts[$worker_idx]}")"
    set +e
    wait_cmd_with_timeout_ms "$pid" "$worker_timeout_ms" "testgen-worker-$((worker_idx + 1))"
    worker_status=$?
    set -e
    if [[ "$worker_status" -eq "$AGENT_TIMEOUT_EXIT" ]]; then
      aih_err "TestGen worker $((worker_idx + 1)) timed out after ${worker_timeout_ms}ms"
      wave_failed=$((wave_failed + 1))
    elif [[ "$worker_status" -ne 0 ]]; then
      wave_failed=$((wave_failed + 1))
    fi
    worker_idx=$((worker_idx + 1))
  done

  if [[ "$wave_failed" -gt 0 ]]; then
    aih_warn "Wave ${wave}: ${wave_failed} worker(s) reported incomplete assignments"
  fi

  if all_test_cases_current; then
    echo "TESTGEN_COMPLETE"
    exit 0
  fi
done

aih_err "Max TestGen waves (${max}) reached"
read -r pending remaining < <(count_pending_requirement_tags)
aih_info "Remaining requirement tags without test cases: ${pending} / ${remaining}"
exit 1
