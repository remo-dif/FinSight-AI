import { ComponentPropsWithoutRef, ElementType } from "react";
import { cn } from "@/lib/utils";

type PanelProps<T extends ElementType = "div"> = {
  as?: T;
} & ComponentPropsWithoutRef<T>;

export function Panel<T extends ElementType = "div">({ as, className, ...props }: PanelProps<T>) {
  const Component = as ?? "div";

  return (
    <Component
      className={cn("rounded-lg border border-border bg-panel p-5 shadow-soft", className)}
      {...props}
    />
  );
}
