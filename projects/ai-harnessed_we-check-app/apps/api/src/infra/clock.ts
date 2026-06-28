/** Injectable clock for session expiry integration tests (NFR-16). */
let offsetMs = 0;

export function now(): Date {
  return new Date(Date.now() + offsetMs);
}

export function nowMs(): number {
  return Date.now() + offsetMs;
}

export function setClock(isoOrDate: string | Date): void {
  const target = typeof isoOrDate === "string" ? new Date(isoOrDate) : isoOrDate;
  offsetMs = target.getTime() - Date.now();
}

export function advanceClock(ms: number): void {
  offsetMs += ms;
}

export function resetClock(): void {
  offsetMs = 0;
}
