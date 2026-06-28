import type { SessionStatus } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import type { SessionRecord } from "./types.js";

interface SessionRow {
  id: string;
  instructor_id: string;
  class_id: string;
  subject_id: string;
  title: string;
  room_name: string;
  room_latitude: number | null;
  room_longitude: number | null;
  gps_radius_meters: number;
  scheduled_start: Date;
  status: SessionStatus;
  opened_at: Date | null;
  closed_at: Date | null;
  version: number;
  created_at: Date;
  updated_at: Date;
}

function mapRow(row: SessionRow): SessionRecord {
  return {
    id: row.id,
    instructorId: row.instructor_id,
    classId: row.class_id,
    subjectId: row.subject_id,
    title: row.title,
    roomName: row.room_name,
    roomLatitude: row.room_latitude,
    roomLongitude: row.room_longitude,
    gpsRadiusMeters: row.gps_radius_meters,
    scheduledStart: row.scheduled_start,
    status: row.status,
    openedAt: row.opened_at,
    closedAt: row.closed_at,
    version: row.version,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export class SessionRepository {
  constructor(private readonly db: DbPool) {}

  async findById(id: string): Promise<SessionRecord | null> {
    const result = await this.db.query<SessionRow>(
      `SELECT id, instructor_id, class_id, subject_id, title, room_name,
              room_latitude, room_longitude, gps_radius_meters, scheduled_start,
              status, opened_at, closed_at, version, created_at, updated_at
       FROM sessions WHERE id = $1`,
      [id],
    );
    const row = result.rows[0];
    return row ? mapRow(row) : null;
  }

  async findByIdForUpdate(
    client: DbPool | { query: DbPool["query"] },
    id: string,
  ): Promise<SessionRecord | null> {
    const result = await client.query<SessionRow>(
      `SELECT id, instructor_id, class_id, subject_id, title, room_name,
              room_latitude, room_longitude, gps_radius_meters, scheduled_start,
              status, opened_at, closed_at, version, created_at, updated_at
       FROM sessions WHERE id = $1 FOR UPDATE`,
      [id],
    );
    const row = result.rows[0];
    return row ? mapRow(row) : null;
  }

  async insert(
    record: Omit<SessionRecord, "createdAt" | "updatedAt" | "version"> & {
      version?: number;
    },
  ): Promise<SessionRecord> {
    const result = await this.db.query<SessionRow>(
      `INSERT INTO sessions (
         id, instructor_id, class_id, subject_id, title, room_name,
         room_latitude, room_longitude, gps_radius_meters, scheduled_start,
         status, opened_at, closed_at, version
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
       RETURNING id, instructor_id, class_id, subject_id, title, room_name,
                 room_latitude, room_longitude, gps_radius_meters, scheduled_start,
                 status, opened_at, closed_at, version, created_at, updated_at`,
      [
        record.id,
        record.instructorId,
        record.classId,
        record.subjectId,
        record.title,
        record.roomName,
        record.roomLatitude,
        record.roomLongitude,
        record.gpsRadiusMeters,
        record.scheduledStart,
        record.status,
        record.openedAt,
        record.closedAt,
        record.version ?? 1,
      ],
    );
    return mapRow(result.rows[0]!);
  }

  async update(
    id: string,
    patch: Partial<
      Pick<
        SessionRecord,
        | "title"
        | "roomName"
        | "roomLatitude"
        | "roomLongitude"
        | "gpsRadiusMeters"
        | "scheduledStart"
        | "status"
        | "openedAt"
        | "closedAt"
      >
    >,
    expectedVersion: number,
    client?: { query: DbPool["query"] },
  ): Promise<SessionRecord | null> {
    const db = client ?? this.db;
    const sets: string[] = ["updated_at = NOW()", "version = version + 1"];
    const values: unknown[] = [id, expectedVersion];
    let idx = 3;

    const fields: [keyof typeof patch, string][] = [
      ["title", "title"],
      ["roomName", "room_name"],
      ["roomLatitude", "room_latitude"],
      ["roomLongitude", "room_longitude"],
      ["gpsRadiusMeters", "gps_radius_meters"],
      ["scheduledStart", "scheduled_start"],
      ["status", "status"],
      ["openedAt", "opened_at"],
      ["closedAt", "closed_at"],
    ];

    for (const [key, column] of fields) {
      if (patch[key] !== undefined) {
        sets.push(`${column} = $${idx}`);
        values.push(patch[key]);
        idx += 1;
      }
    }

    const result = await db.query<SessionRow>(
      `UPDATE sessions SET ${sets.join(", ")}
       WHERE id = $1 AND version = $2
       RETURNING id, instructor_id, class_id, subject_id, title, room_name,
                 room_latitude, room_longitude, gps_radius_meters, scheduled_start,
                 status, opened_at, closed_at, version, created_at, updated_at`,
      values,
    );
    const row = result.rows[0];
    return row ? mapRow(row) : null;
  }

  async listActivePastWindow(now: Date): Promise<SessionRecord[]> {
    const result = await this.db.query<SessionRow>(
      `SELECT id, instructor_id, class_id, subject_id, title, room_name,
              room_latitude, room_longitude, gps_radius_meters, scheduled_start,
              status, opened_at, closed_at, version, created_at, updated_at
       FROM sessions
       WHERE status = 'Active'
         AND scheduled_start + INTERVAL '10 minutes' <= $1`,
      [now],
    );
    return result.rows.map(mapRow);
  }
}
