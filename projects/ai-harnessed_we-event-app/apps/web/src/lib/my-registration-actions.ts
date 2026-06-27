import type { MyRegistrationListItem } from "@/lib/participant-api";
import {
  canSelfCheckIn,
  canSubmitFeedback,
  canViewEligibility,
} from "@/lib/participant-rules";

export interface MyRegistrationQuickActions {
  showCheckIn: boolean;
  showFeedback: boolean;
  showEligibility: boolean;
}

export function deriveMyRegistrationQuickActions(
  item: MyRegistrationListItem,
  now: number = Date.now(),
): MyRegistrationQuickActions {
  return {
    showCheckIn: canSelfCheckIn(
      item.eventState,
      item.state,
      item.checkinOpenAt,
      item.checkinCloseAt,
      item.selfCheckinEnabled ?? true,
      now,
    ),
    showFeedback: canSubmitFeedback(
      item.eventState,
      item.state,
      item.feedbackOpenAt,
      item.feedbackCloseAt,
      now,
    ),
    showEligibility: canViewEligibility(item.eventState, item.state),
  };
}
