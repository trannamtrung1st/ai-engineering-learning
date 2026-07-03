/**
 * NFR-16 — publish performance smoke metric snapshots for CI triage.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { ThresholdVerdict } from "./thresholds.js";
import { PERFORMANCE_SMOKE_THRESHOLDS } from "./thresholds.js";

export type PerformanceSmokeSnapshot = {
  generatedAt: string;
  sliceId: string;
  thresholds: typeof PERFORMANCE_SMOKE_THRESHOLDS;
  sampleSize: number;
  sessionCount: number;
  verdicts: Record<string, ThresholdVerdict>;
  overallPass: boolean;
};

export function buildPerformanceSmokeSnapshot(input: {
  sliceId: string;
  sampleSize: number;
  sessionCount: number;
  verdicts: Record<string, ThresholdVerdict>;
}): PerformanceSmokeSnapshot {
  const overallPass = Object.values(input.verdicts).every((verdict) => verdict.pass);
  return {
    generatedAt: new Date().toISOString(),
    sliceId: input.sliceId,
    thresholds: PERFORMANCE_SMOKE_THRESHOLDS,
    sampleSize: input.sampleSize,
    sessionCount: input.sessionCount,
    verdicts: input.verdicts,
    overallPass,
  };
}

export function publishPerformanceSmokeSnapshot(snapshot: PerformanceSmokeSnapshot): string {
  const dir =
    process.env.PERF_SMOKE_METRICS_DIR ??
    join(process.cwd(), "ai-harness/generated/runs/performance-smoke");
  mkdirSync(dir, { recursive: true });
  const filePath = join(dir, `metrics-${snapshot.generatedAt.replace(/[:.]/g, "-")}.json`);
  writeFileSync(filePath, `${JSON.stringify(snapshot, null, 2)}\n`, "utf8");
  return filePath;
}
