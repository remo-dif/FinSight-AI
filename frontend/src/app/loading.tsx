export default function Loading() {
  return (
    <main className="grid min-h-screen animate-pulse bg-background lg:grid-cols-[244px_minmax(0,1fr)]" aria-label="Loading investigation workspace">
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
    </main>
  );
}
