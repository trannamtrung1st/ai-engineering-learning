"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { ImagePlus, Trash2 } from "lucide-react";

import { EventCoverMedia } from "@/components/participant/event-cover-media";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { validateCoverImageFile } from "@/lib/cover-image";
import {
  deleteEventCoverImage,
  uploadEventCoverImage,
} from "@/lib/organizer-api";

export interface EventCoverPickerHandle {
  uploadPendingCover: (eventId: string) => Promise<string | null>;
  hasPendingFile: () => boolean;
}

export interface EventCoverPickerProps {
  token: string;
  eventId?: string;
  initialCoverImageUrl?: string;
  onCoverChange?: (coverImageUrl: string | null) => void;
}

export const EventCoverPicker = forwardRef<
  EventCoverPickerHandle,
  EventCoverPickerProps
>(function EventCoverPicker(
  { token, eventId, initialCoverImageUrl, onCoverChange },
  ref,
) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [coverImageUrl, setCoverImageUrl] = useState<string | null>(
    initialCoverImageUrl ?? null,
  );
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setCoverImageUrl(initialCoverImageUrl ?? null);
  }, [initialCoverImageUrl]);

  useEffect(() => {
    if (!pendingFile) {
      setPreviewUrl(null);
      return;
    }

    const objectUrl = URL.createObjectURL(pendingFile);
    setPreviewUrl(objectUrl);
    return () => {
      URL.revokeObjectURL(objectUrl);
    };
  }, [pendingFile]);

  const displayUrl = previewUrl ?? coverImageUrl;

  async function applyFile(file: File) {
    const validationError = validateCoverImageFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }

    setError(null);

    if (!eventId) {
      setPendingFile(file);
      return;
    }

    setBusy(true);
    setUploadProgress(0);
    try {
      const updated = await uploadEventCoverImage(token, eventId, file, (percent) => {
        setUploadProgress(percent);
      });
      setPendingFile(null);
      setCoverImageUrl(updated.coverImageUrl ?? null);
      onCoverChange?.(updated.coverImageUrl ?? null);
    } catch (uploadError) {
      setError(
        uploadError instanceof Error
          ? uploadError.message
          : "Could not upload cover image.",
      );
    } finally {
      setBusy(false);
      setUploadProgress(null);
    }
  }

  async function handleRemove() {
    setError(null);
    setPendingFile(null);

    if (!eventId) {
      return;
    }

    if (!coverImageUrl) {
      return;
    }

    setBusy(true);
    try {
      const updated = await deleteEventCoverImage(token, eventId);
      setCoverImageUrl(updated.coverImageUrl ?? null);
      onCoverChange?.(updated.coverImageUrl ?? null);
    } catch (deleteError) {
      setError(
        deleteError instanceof Error
          ? deleteError.message
          : "Could not remove cover image.",
      );
    } finally {
      setBusy(false);
    }
  }

  useImperativeHandle(ref, () => ({
    hasPendingFile: () => pendingFile !== null,
    uploadPendingCover: async (targetEventId: string) => {
      if (!pendingFile) {
        return coverImageUrl;
      }

      setBusy(true);
      setUploadProgress(0);
      setError(null);
      try {
        const updated = await uploadEventCoverImage(
          token,
          targetEventId,
          pendingFile,
          (percent) => {
            setUploadProgress(percent);
          },
        );
        setPendingFile(null);
        setCoverImageUrl(updated.coverImageUrl ?? null);
        onCoverChange?.(updated.coverImageUrl ?? null);
        return updated.coverImageUrl ?? null;
      } catch (uploadError) {
        const message =
          uploadError instanceof Error
            ? uploadError.message
            : "Could not upload cover image.";
        setError(message);
        throw uploadError;
      } finally {
        setBusy(false);
        setUploadProgress(null);
      }
    },
  }));

  return (
    <section className="space-y-4" data-testid="event-cover-picker">
      <div>
        <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
          Cover image
        </h2>
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          JPEG, PNG, or WebP up to 5 MB. Shown on event discovery cards and detail pages.
        </p>
      </div>

      {error ? (
        <Alert variant="error" title="Cover image">
          {error}
        </Alert>
      ) : null}

      <div className="space-y-3">
        {displayUrl ? (
          <div className="relative max-w-xl">
            {/* eslint-disable-next-line @next/next/no-img-element -- blob preview before upload */}
            {previewUrl ? (
              <img
                src={previewUrl}
                alt="Selected cover preview"
                className="aspect-video w-full rounded-[var(--radius-md)] object-cover"
                data-testid="event-cover-preview"
              />
            ) : (
              <EventCoverMedia
                coverImageUrl={coverImageUrl}
                alt="Current event cover"
                variant="thumbnail"
              />
            )}
          </div>
        ) : (
          <EventCoverMedia
            coverImageUrl={null}
            alt="Event cover placeholder"
            variant="thumbnail"
            className="max-w-xl"
          />
        )}

        {uploadProgress !== null ? (
          <div className="max-w-xl space-y-1" data-testid="event-cover-upload-progress">
            <div
              className="h-2 overflow-hidden rounded-full bg-[var(--color-bg-subtle)]"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={uploadProgress}
              aria-label="Cover image upload progress"
            >
              <div
                className="h-full bg-[var(--color-action-primary-bg)] transition-[width] duration-150"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
            <p className="text-[length:var(--font-size-xs)] text-[var(--color-text-secondary)]">
              Uploading… {uploadProgress}%
            </p>
          </div>
        ) : null}

        <div className="flex flex-wrap gap-2">
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            data-testid="event-cover-file-input"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) {
                void applyFile(file);
              }
            }}
          />
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
          >
            <ImagePlus className="h-4 w-4" aria-hidden />
            {displayUrl ? "Replace cover" : "Choose cover"}
          </Button>
          {displayUrl ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => void handleRemove()}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
              Remove
            </Button>
          ) : null}
        </div>
      </div>
    </section>
  );
});
