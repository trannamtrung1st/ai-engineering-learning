"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Form, FormField } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  datetimeLocalToIso,
  defaultEventWindowOffsets,
  isoToDatetimeLocal,
} from "@/lib/datetime-local";
import { DEFAULT_ORGANIZATION_ID } from "@/lib/organizer-api";

const eventFormSchema = z
  .object({
    name: z.string().trim().min(1, "Event name is required."),
    description: z.string().optional(),
    location: z.string().optional(),
    startAt: z.string().min(1, "Start date/time is required."),
    endAt: z.string().min(1, "End date/time is required."),
    capacity: z.coerce.number().int().min(1, "Capacity must be at least 1."),
    waitlistEnabled: z.boolean(),
    registrationOpenAt: z.string().min(1, "Registration open time is required."),
    registrationCloseAt: z.string().min(1, "Registration close time is required."),
    checkinOpenAt: z.string().min(1, "Check-in open time is required."),
    checkinCloseAt: z.string().min(1, "Check-in close time is required."),
    feedbackRequired: z.boolean(),
    feedbackOpenAt: z.string().min(1, "Feedback open time is required."),
    feedbackCloseAt: z.string().min(1, "Feedback close time is required."),
  })
  .superRefine((values, ctx) => {
    const start = new Date(values.startAt).getTime();
    const end = new Date(values.endAt).getTime();
    if (!Number.isNaN(start) && !Number.isNaN(end) && end <= start) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "End time must be after start time.",
        path: ["endAt"],
      });
    }

    const regOpen = new Date(values.registrationOpenAt).getTime();
    const regClose = new Date(values.registrationCloseAt).getTime();
    if (!Number.isNaN(regOpen) && !Number.isNaN(regClose) && regClose <= regOpen) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Registration close must be after registration open.",
        path: ["registrationCloseAt"],
      });
    }

    const checkinOpen = new Date(values.checkinOpenAt).getTime();
    const checkinClose = new Date(values.checkinCloseAt).getTime();
    if (
      !Number.isNaN(checkinOpen) &&
      !Number.isNaN(checkinClose) &&
      checkinClose <= checkinOpen
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Check-in close must be after check-in open.",
        path: ["checkinCloseAt"],
      });
    }
  });

export type EventFormValues = z.infer<typeof eventFormSchema>;

export interface EventFormInitialValues {
  name?: string;
  description?: string;
  location?: string;
  startAt?: string;
  endAt?: string;
  ruleConfig?: {
    capacity?: number;
    waitlistEnabled?: boolean;
    registrationOpenAt?: string;
    registrationCloseAt?: string;
    checkinOpenAt?: string;
    checkinCloseAt?: string;
    feedbackRequired?: boolean;
    feedbackOpenAt?: string;
    feedbackCloseAt?: string;
  };
}

function buildDefaults(initial?: EventFormInitialValues): EventFormValues {
  const windows = defaultEventWindowOffsets();
  const rule = initial?.ruleConfig;

  return {
    name: initial?.name ?? "",
    description: initial?.description ?? "",
    location: initial?.location ?? "",
    startAt: isoToDatetimeLocal(initial?.startAt ?? windows.startAt),
    endAt: isoToDatetimeLocal(initial?.endAt ?? windows.endAt),
    capacity: rule?.capacity ?? 50,
    waitlistEnabled: rule?.waitlistEnabled ?? true,
    registrationOpenAt: isoToDatetimeLocal(
      rule?.registrationOpenAt ?? windows.registrationOpenAt,
    ),
    registrationCloseAt: isoToDatetimeLocal(
      rule?.registrationCloseAt ?? windows.registrationCloseAt,
    ),
    checkinOpenAt: isoToDatetimeLocal(rule?.checkinOpenAt ?? windows.checkinOpenAt),
    checkinCloseAt: isoToDatetimeLocal(rule?.checkinCloseAt ?? windows.checkinCloseAt),
    feedbackRequired: rule?.feedbackRequired ?? true,
    feedbackOpenAt: isoToDatetimeLocal(rule?.feedbackOpenAt ?? windows.feedbackOpenAt),
    feedbackCloseAt: isoToDatetimeLocal(rule?.feedbackCloseAt ?? windows.feedbackCloseAt),
  };
}

export function toCreateEventPayload(values: EventFormValues) {
  return {
    organizationId: DEFAULT_ORGANIZATION_ID,
    name: values.name.trim(),
    description: values.description?.trim() || undefined,
    location: values.location?.trim() || undefined,
    startAt: datetimeLocalToIso(values.startAt),
    endAt: datetimeLocalToIso(values.endAt),
    ruleConfig: {
      capacity: values.capacity,
      waitlistEnabled: values.waitlistEnabled,
      registrationOpenAt: datetimeLocalToIso(values.registrationOpenAt),
      registrationCloseAt: datetimeLocalToIso(values.registrationCloseAt),
      checkinOpenAt: datetimeLocalToIso(values.checkinOpenAt),
      checkinCloseAt: datetimeLocalToIso(values.checkinCloseAt),
      feedbackRequired: values.feedbackRequired,
      feedbackOpenAt: datetimeLocalToIso(values.feedbackOpenAt),
      feedbackCloseAt: datetimeLocalToIso(values.feedbackCloseAt),
    },
  };
}

export function toUpdateEventPayload(values: EventFormValues) {
  return {
    name: values.name.trim(),
    description: values.description?.trim() || undefined,
    location: values.location?.trim() || undefined,
    startAt: datetimeLocalToIso(values.startAt),
    endAt: datetimeLocalToIso(values.endAt),
    ruleConfig: {
      capacity: values.capacity,
      waitlistEnabled: values.waitlistEnabled,
      registrationOpenAt: datetimeLocalToIso(values.registrationOpenAt),
      registrationCloseAt: datetimeLocalToIso(values.registrationCloseAt),
      checkinOpenAt: datetimeLocalToIso(values.checkinOpenAt),
      checkinCloseAt: datetimeLocalToIso(values.checkinCloseAt),
      feedbackRequired: values.feedbackRequired,
      feedbackOpenAt: datetimeLocalToIso(values.feedbackOpenAt),
      feedbackCloseAt: datetimeLocalToIso(values.feedbackCloseAt),
    },
  };
}

export interface EventFormProps {
  initial?: EventFormInitialValues;
  submitLabel: string;
  onSubmit: (values: EventFormValues) => Promise<void>;
}

export function EventForm({ initial, submitLabel, onSubmit }: EventFormProps) {
  const form = useForm<EventFormValues>({
    defaultValues: buildDefaults(initial),
    mode: "onBlur",
  });
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  return (
    <Form
      form={form}
      onSubmit={async (rawValues) => {
        setSubmitError(null);
        setSubmitting(true);
        try {
          const parsed = eventFormSchema.safeParse(rawValues);
          if (!parsed.success) {
            for (const issue of parsed.error.issues) {
              const path = issue.path[0];
              if (typeof path === "string") {
                form.setError(path as keyof EventFormValues, {
                  message: issue.message,
                });
              }
            }
            return;
          }
          await onSubmit(parsed.data);
        } catch (error) {
          setSubmitError(
            error instanceof Error ? error.message : "Could not save event.",
          );
        } finally {
          setSubmitting(false);
        }
      }}
      className="max-w-3xl space-y-8"
    >
      {submitError ? (
        <Alert variant="error" title="Could not save event">
          {submitError}
        </Alert>
      ) : null}

      <section className="space-y-4">
        <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
          Basic details
        </h2>
        <FormField
          name="name"
          control={form.control}
          label="Event name"
          required
          render={({ field, fieldState }) => (
            <Input
              id={String(field.name)}
              error={Boolean(fieldState.error)}
              {...field}
            />
          )}
        />
        <FormField
          name="description"
          control={form.control}
          label="Description"
          render={({ field }) => <Textarea id={String(field.name)} rows={4} {...field} />}
        />
        <FormField
          name="location"
          control={form.control}
          label="Location"
          render={({ field }) => <Input id={String(field.name)} {...field} />}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            name="startAt"
            control={form.control}
            label="Start (local time)"
            required
            helperText="Times are saved in UTC and shown in your timezone."
            render={({ field, fieldState }) => (
              <Input
                id={String(field.name)}
                type="datetime-local"
                error={Boolean(fieldState.error)}
                {...field}
              />
            )}
          />
          <FormField
            name="endAt"
            control={form.control}
            label="End (local time)"
            required
            render={({ field, fieldState }) => (
              <Input
                id={String(field.name)}
                type="datetime-local"
                error={Boolean(fieldState.error)}
                {...field}
              />
            )}
          />
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
          Capacity and waitlist
        </h2>
        <FormField
          name="capacity"
          control={form.control}
          label="Capacity"
          required
          render={({ field, fieldState }) => (
            <Input
              id={String(field.name)}
              type="number"
              min={1}
              error={Boolean(fieldState.error)}
              {...field}
            />
          )}
        />
        <FormField
          name="waitlistEnabled"
          control={form.control}
          label="Waitlist"
          render={({ field }) => (
            <label htmlFor={String(field.name)} className="flex items-center gap-2">
              <Checkbox
                id={String(field.name)}
                checked={field.value}
                onCheckedChange={(checked) => field.onChange(checked === true)}
              />
              <span className="text-[length:var(--font-size-sm)]">
                Enable waitlist when capacity is full
              </span>
            </label>
          )}
        />
      </section>

      <section className="space-y-4">
        <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
          Registration window
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            name="registrationOpenAt"
            control={form.control}
            label="Opens"
            required
            render={({ field, fieldState }) => (
              <Input
                id={String(field.name)}
                type="datetime-local"
                error={Boolean(fieldState.error)}
                {...field}
              />
            )}
          />
          <FormField
            name="registrationCloseAt"
            control={form.control}
            label="Closes"
            required
            render={({ field, fieldState }) => (
              <Input
                id={String(field.name)}
                type="datetime-local"
                error={Boolean(fieldState.error)}
                {...field}
              />
            )}
          />
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
          Check-in window
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            name="checkinOpenAt"
            control={form.control}
            label="Opens"
            required
            render={({ field, fieldState }) => (
              <Input
                id={String(field.name)}
                type="datetime-local"
                error={Boolean(fieldState.error)}
                {...field}
              />
            )}
          />
          <FormField
            name="checkinCloseAt"
            control={form.control}
            label="Closes"
            required
            render={({ field, fieldState }) => (
              <Input
                id={String(field.name)}
                type="datetime-local"
                error={Boolean(fieldState.error)}
                {...field}
              />
            )}
          />
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
          Feedback and certificate rules
        </h2>
        <FormField
          name="feedbackRequired"
          control={form.control}
          label="Feedback"
          render={({ field }) => (
            <label htmlFor={String(field.name)} className="flex items-center gap-2">
              <Checkbox
                id={String(field.name)}
                checked={field.value}
                onCheckedChange={(checked) => field.onChange(checked === true)}
              />
              <span className="text-[length:var(--font-size-sm)]">
                Require feedback before eligibility finalization
              </span>
            </label>
          )}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            name="feedbackOpenAt"
            control={form.control}
            label="Feedback opens"
            required
            render={({ field, fieldState }) => (
              <Input
                id={String(field.name)}
                type="datetime-local"
                error={Boolean(fieldState.error)}
                {...field}
              />
            )}
          />
          <FormField
            name="feedbackCloseAt"
            control={form.control}
            label="Feedback closes"
            required
            render={({ field, fieldState }) => (
              <Input
                id={String(field.name)}
                type="datetime-local"
                error={Boolean(fieldState.error)}
                {...field}
              />
            )}
          />
        </div>
      </section>

      <Button type="submit" loading={submitting} disabled={submitting}>
        {submitting ? "Saving…" : submitLabel}
      </Button>
    </Form>
  );
}
