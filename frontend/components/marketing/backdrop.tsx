/**
 * Daylight behind the public pages.
 *
 * Entirely CSS — no images, no canvas, no JS — so it costs nothing to load and
 * renders identically on the server. Three pale, slowly drifting washes plus a
 * dot field, all pinned behind the content and kept faint enough that text on
 * top never loses contrast.
 */
export function Backdrop({ dots = true }: { dots?: boolean }) {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      {/* The canvas itself, warmed with a wash from the top. */}
      <div className="absolute inset-0 bg-gradient-to-b from-white via-canvas to-canvas" />

      {/* Aurora. Out-of-phase durations keep the three from ever lining up. */}
      <div className="aurora-blob absolute -left-[12%] -top-[18%] h-[38rem] w-[38rem] bg-brand/20 animate-drift" />
      <div
        className="aurora-blob absolute -right-[14%] top-[2%] h-[32rem] w-[32rem] bg-info/16 animate-drift"
        style={{ animationDelay: "-8s", animationDuration: "28s" }}
      />
      <div
        className="aurora-blob absolute left-[22%] top-[52%] h-[34rem] w-[34rem] bg-grape/14 animate-drift"
        style={{ animationDelay: "-15s", animationDuration: "32s" }}
      />

      {dots ? <div className="dot-field absolute inset-x-0 top-0 h-[70vh]" /> : null}

      {/* Settles the very top back to white so sticky chrome keeps its edge. */}
      <div className="absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-white to-transparent" />
    </div>
  );
}
