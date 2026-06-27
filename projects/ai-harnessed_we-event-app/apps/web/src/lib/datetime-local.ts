/** Convert ISO instant to `datetime-local` input value (local timezone). */
export function isoToDatetimeLocal(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Parse `datetime-local` value to ISO string (UTC). */
export function datetimeLocalToIso(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new Error("Invalid date/time value.");
  }
  return date.toISOString();
}

export function defaultEventWindowOffsets(): {
  startAt: string;
  endAt: string;
  registrationOpenAt: string;
  registrationCloseAt: string;
  checkinOpenAt: string;
  checkinCloseAt: string;
  feedbackOpenAt: string;
  feedbackCloseAt: string;
} {
  const start = new Date();
  start.setDate(start.getDate() + 14);
  start.setHours(9, 0, 0, 0);

  const end = new Date(start);
  end.setHours(17, 0, 0, 0);

  const regOpen = new Date(start);
  regOpen.setDate(regOpen.getDate() - 7);
  regOpen.setHours(9, 0, 0, 0);

  const regClose = new Date(start);
  regClose.setHours(8, 0, 0, 0);

  const checkinOpen = new Date(start);
  checkinOpen.setHours(8, 30, 0, 0);

  const checkinClose = new Date(end);
  checkinClose.setHours(18, 0, 0, 0);

  const feedbackOpen = new Date(end);
  feedbackOpen.setHours(17, 30, 0, 0);

  const feedbackClose = new Date(end);
  feedbackClose.setDate(feedbackClose.getDate() + 7);
  feedbackClose.setHours(23, 59, 0, 0);

  return {
    startAt: start.toISOString(),
    endAt: end.toISOString(),
    registrationOpenAt: regOpen.toISOString(),
    registrationCloseAt: regClose.toISOString(),
    checkinOpenAt: checkinOpen.toISOString(),
    checkinCloseAt: checkinClose.toISOString(),
    feedbackOpenAt: feedbackOpen.toISOString(),
    feedbackCloseAt: feedbackClose.toISOString(),
  };
}
