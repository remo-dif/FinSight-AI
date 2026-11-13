"use client";

import Link from "next/link";
import type { Route } from "next";
import {
  BriefcaseBusiness,
  ChevronLeft,
  ChevronRight,
  Database,
  FileSearch,
  Gauge,
  Network,
  Settings,
  type LucideIcon
} from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

export type MobileNavigationItem = {
  id: "triage" | "cases" | "graph" | "evidence" | "data" | "controls";
  label: string;
  href: `/${string}`;
  comingSoon?: boolean;
};

const icons: Record<MobileNavigationItem["id"], LucideIcon> = {
  triage: Gauge,
  cases: BriefcaseBusiness,
  graph: Network,
  evidence: FileSearch,
  data: Database,
  controls: Settings
};

export function MobileNavigation({
  activeRoute,
  items
}: {
  activeRoute: MobileNavigationItem["id"];
  items: MobileNavigationItem[];
}) {
  const navigationRef = useRef<HTMLElement>(null);
  const itemRefs = useRef(new Map<MobileNavigationItem["id"], HTMLAnchorElement>());
  const [overflow, setOverflow] = useState({ start: false, end: false });

  const updateOverflow = useCallback(() => {
    const navigation = navigationRef.current;
    if (!navigation) return;
    const maximumScroll = Math.max(navigation.scrollWidth - navigation.clientWidth, 0);
    setOverflow({
      start: navigation.scrollLeft > 1,
      end: navigation.scrollLeft < maximumScroll - 1
    });
  }, []);

  useLayoutEffect(() => {
    const navigation = navigationRef.current;
    const activeItem = itemRefs.current.get(activeRoute);
    if (!navigation || !activeItem) return;

    const itemStart = activeItem.offsetLeft;
    const itemEnd = itemStart + activeItem.offsetWidth;
    const visibleStart = navigation.scrollLeft;
    const visibleEnd = visibleStart + navigation.clientWidth;
    const edgePadding = 8;
    let nextScroll = visibleStart;

    if (itemStart < visibleStart + edgePadding) {
      nextScroll = Math.max(itemStart - edgePadding, 0);
    } else if (itemEnd > visibleEnd - edgePadding) {
      nextScroll = itemEnd - navigation.clientWidth + edgePadding;
    }

    navigation.scrollTo({ left: nextScroll, behavior: "auto" });
    const frame = window.requestAnimationFrame(updateOverflow);
    return () => window.cancelAnimationFrame(frame);
  }, [activeRoute, updateOverflow]);

  useEffect(() => {
    const navigation = navigationRef.current;
    if (!navigation) return;

    updateOverflow();
    navigation.addEventListener("scroll", updateOverflow, { passive: true });
    const observer = new ResizeObserver(updateOverflow);
    observer.observe(navigation);

    return () => {
      navigation.removeEventListener("scroll", updateOverflow);
      observer.disconnect();
    };
  }, [updateOverflow]);

  return (
    <div className="relative lg:hidden">
      <nav
        ref={navigationRef}
        className="flex gap-0 overflow-x-auto border-b border-border px-0 py-0 text-sm font-medium [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        aria-label="Mobile navigation"
      >
        {items.map((item) => {
          const Icon = icons[item.id];
          const isActive = item.id === activeRoute;
          return (
            <Link
              ref={(element) => {
                if (element) itemRefs.current.set(item.id, element);
                else itemRefs.current.delete(item.id);
              }}
              key={item.label}
              className={`inline-flex min-h-[44px] shrink-0 items-center justify-center gap-1.5 border-b border-r border-border px-3 py-2 text-center transition ${
                isActive
                  ? "border-b-accent bg-accent/10 text-accent"
                  : "bg-white text-muted hover:border-accent/60 hover:text-foreground"
              }`}
              href={item.href as Route}
              aria-current={isActive ? "page" : undefined}
            >
              <Icon aria-hidden className="h-4 w-4" />
              <span className="whitespace-nowrap">{item.label}</span>
              {item.comingSoon ? (
                <span className="inline-flex items-center rounded-full border border-current/20 bg-current/5 px-1.5 py-0.5 text-xs font-semibold uppercase leading-none tracking-wide">
                  Coming soon
                </span>
              ) : null}
            </Link>
          );
        })}
      </nav>

      {overflow.start ? (
        <span
          aria-hidden="true"
          data-scroll-indicator="start"
          className="pointer-events-none absolute inset-y-0 left-0 flex w-8 items-center bg-gradient-to-r from-panel via-panel/90 to-transparent pl-0.5 text-muted"
        >
          <ChevronLeft className="h-4 w-4" />
        </span>
      ) : null}
      {overflow.end ? (
        <span
          aria-hidden="true"
          data-scroll-indicator="end"
          className="pointer-events-none absolute inset-y-0 right-0 flex w-8 items-center justify-end bg-gradient-to-l from-panel via-panel/90 to-transparent pr-0.5 text-muted"
        >
          <ChevronRight className="h-4 w-4" />
        </span>
      ) : null}
    </div>
  );
}
