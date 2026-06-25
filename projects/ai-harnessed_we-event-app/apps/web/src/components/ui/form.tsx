"use client";

import {
  Controller,
  FormProvider,
  type ControllerProps,
  type FieldPath,
  type FieldValues,
  type UseFormReturn,
} from "react-hook-form";

import { Field } from "@/components/ui/field";
import { cn } from "@/lib/cn";

export function Form<T extends FieldValues>({
  form,
  onSubmit,
  children,
  className,
}: {
  form: UseFormReturn<T>;
  onSubmit: (values: T) => void | Promise<void>;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <FormProvider {...form}>
      <form
        className={cn("space-y-[var(--gap-component)]", className)}
        onSubmit={form.handleSubmit(onSubmit)}
        noValidate
      >
        {children}
      </form>
    </FormProvider>
  );
}

export function FormField<
  TFieldValues extends FieldValues,
  TName extends FieldPath<TFieldValues>,
>({
  name,
  control,
  label,
  helperText,
  required,
  render,
}: {
  name: TName;
  control: ControllerProps<TFieldValues, TName>["control"];
  label: string;
  helperText?: string;
  required?: boolean;
  render: ControllerProps<TFieldValues, TName>["render"];
}) {
  return (
    <Controller
      name={name}
      control={control}
      render={(controllerProps) => {
        const errorText =
          typeof controllerProps.fieldState.error?.message === "string"
            ? controllerProps.fieldState.error.message
            : undefined;

        return (
          <Field
            id={String(name)}
            label={label}
            helperText={helperText}
            errorText={errorText}
            required={required}
          >
            {render(controllerProps)}
          </Field>
        );
      }}
    />
  );
}
