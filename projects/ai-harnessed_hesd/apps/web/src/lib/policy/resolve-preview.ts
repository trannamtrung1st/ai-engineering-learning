import type { EffectivePolicyResponse, PolicyScopeType } from "../api/policy-api.js";
import { POLICY_PRECEDENCE_CHAIN } from "../i18n/policy-fields.js";

export const PREVIEW_FIELD_KEYS = [
  "presentWindowMinutes",
  "lateWindowMinutes",
  "manualEditWindowHours",
  "gpsRequired",
  "gpsRadiusMeters",
] as const;

export type PreviewFieldKey = (typeof PREVIEW_FIELD_KEYS)[number];

export interface PreviewField {
  key: PreviewFieldKey;
  value: unknown;
  source: PolicyScopeType;
}

export interface PolicyPreviewState {
  precedenceChain: PolicyScopeType[];
  fields: PreviewField[];
}

export function mergeDraftIntoEffectivePreview(
  base: EffectivePolicyResponse,
  draftScope: PolicyScopeType,
  draftFields: Partial<Record<PreviewFieldKey, unknown>>,
): PolicyPreviewState {
  const fields: PreviewField[] = PREVIEW_FIELD_KEYS.map((key) => {
    if (draftFields[key] !== undefined && draftScope) {
      return {
        key,
        value: draftFields[key],
        source: draftScope,
      };
    }
    return {
      key,
      value: base.values[key],
      source: base.sources[key] ?? "Institution",
    };
  });

  return {
    precedenceChain: POLICY_PRECEDENCE_CHAIN,
    fields,
  };
}
