"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import {
  useForm,
  type DefaultValues,
  type UseFormReturn,
} from "react-hook-form";
import type { z } from "zod";

export function useZodForm<TSchema extends z.ZodTypeAny>(
  schema: TSchema,
  options?: {
    defaultValues?: DefaultValues<z.infer<TSchema>>;
  },
): UseFormReturn<z.infer<TSchema>> {
  return useForm<z.infer<TSchema>>({
    resolver: zodResolver(schema),
    defaultValues: options?.defaultValues,
    mode: "onBlur",
  });
}
