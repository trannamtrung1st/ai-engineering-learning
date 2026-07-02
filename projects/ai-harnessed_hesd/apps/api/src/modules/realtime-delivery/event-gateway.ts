import { EventEmitter } from "node:events";
import { randomUUID } from "node:crypto";
import type { OperationalTelemetryEvent, RealtimeRosterEvent } from "./types.js";

type RosterListener = (event: RealtimeRosterEvent) => void;
type TelemetryListener = (event: OperationalTelemetryEvent) => void;

const MAX_TELEMETRY_EVENTS = 500;

export class RealtimeDeliveryGateway {
  private readonly emitter = new EventEmitter();
  private readonly telemetry: OperationalTelemetryEvent[] = [];

  subscribeToRoster(classSessionId: string, listener: RosterListener): () => void {
    const eventName = this.rosterEventName(classSessionId);
    this.emitter.on(eventName, listener);
    return () => this.emitter.off(eventName, listener);
  }

  subscribeToTelemetry(listener: TelemetryListener): () => void {
    this.emitter.on("telemetry", listener);
    return () => this.emitter.off("telemetry", listener);
  }

  publishRosterUpdate(event: Omit<RealtimeRosterEvent, "eventId" | "occurredAt" | "type">): RealtimeRosterEvent {
    const payload: RealtimeRosterEvent = {
      ...event,
      eventId: randomUUID(),
      type: "RosterUpdated",
      occurredAt: new Date().toISOString(),
    };
    this.emitter.emit(this.rosterEventName(event.classSessionId), payload);
    return payload;
  }

  publishTelemetry(event: OperationalTelemetryEvent): void {
    this.telemetry.push(event);
    if (this.telemetry.length > MAX_TELEMETRY_EVENTS) {
      this.telemetry.splice(0, this.telemetry.length - MAX_TELEMETRY_EVENTS);
    }
    this.emitter.emit("telemetry", event);
  }

  telemetrySnapshot(filter?: { classSessionId?: string; type?: OperationalTelemetryEvent["type"] }): OperationalTelemetryEvent[] {
    return this.telemetry.filter((event) => {
      if (filter?.classSessionId && event.classSessionId !== filter.classSessionId) return false;
      if (filter?.type && event.type !== filter.type) return false;
      return true;
    });
  }

  clearForTests(): void {
    this.telemetry.splice(0);
    this.emitter.removeAllListeners();
  }

  private rosterEventName(classSessionId: string): string {
    return `roster:${classSessionId}`;
  }
}

export function formatServerSentEvent(
  eventName: string,
  payload: RealtimeRosterEvent,
): string {
  return `event: ${eventName}\nid: ${payload.eventId}\ndata: ${JSON.stringify(payload)}\n\n`;
}

export const realtimeDeliveryGateway = new RealtimeDeliveryGateway();
