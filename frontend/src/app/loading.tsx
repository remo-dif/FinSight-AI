import { LoadingStatus } from "@/components/loading-status";

export default function Loading() {
  return (
    <main
      className="min-h-screen bg-background"
      aria-busy="true"
      aria-describedby="workspace-loading-status"
    >
      <LoadingStatus />
      <div
        className="grid min-h-screen motion-safe:animate-pulse lg:grid-cols-[244px_minmax(0,1fr)]"
        aria-hidden="true"
      >
        <div className="hidden border-r border-border bg-panel lg:block" />
        <div>
          <div className="h-16 border-b border-border bg-panel" />
          <div className="space-y-4 p-4 sm:p-6">
            <div className="h-24 rounded-lg bg-border/50" />
            <div className="h-16 rounded-lg bg-border/50" />
            <div className="grid gap-4 xl:grid-cols-[190px_minmax(0,1fr)_350px]">
              <div className="h-72 rounded-lg bg-border/50" />
              <div className="h-96 rounded-lg bg-border/50" />
              <div className="h-96 rounded-lg bg-border/50" />
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
