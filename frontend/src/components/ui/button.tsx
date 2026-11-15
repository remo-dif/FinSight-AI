import { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type ButtonVariant = "primary" | "secondary" | "text";
type ButtonSize = "sm" | "md" | "touch" | "icon";

const variants: Record<ButtonVariant, string> = {
  primary: "border-transparent bg-accent text-white shadow-sm hover:brightness-95",
  secondary: "border-border bg-white text-foreground hover:border-accent/60",
  text: "h-auto border-transparent bg-transparent px-0 text-accent shadow-none underline-offset-4 hover:underline"
};

const sizes: Record<ButtonSize, string> = {
  sm: "h-9 px-3",
  md: "h-10 px-4",
  touch: "min-h-11 px-3",
  icon: "h-9 w-9 px-0"
};

export function Button({
  className,
  variant = "primary",
  size = "md",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md border text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-60",
        variants[variant],
        sizes[size],
        className
      )}
      {...props}
    />
  );
}
