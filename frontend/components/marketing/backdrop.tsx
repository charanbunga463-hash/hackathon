/**
 * The atmosphere behind the public pages.
 *
 * Entirely CSS — no images, no canvas, no JS — so it costs nothing to load and
 * renders identically on the server. Everything is built from the theme tokens,
 * which is why it reads as daylight in the light theme and deep space in the
 * dark one without a second set of colours.
 */
export function Backdrop({ floor = true }: { floor?: boolean }) {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
    >
      {/* Aurora field. Three slow, out-of-phase blobs; the offsets keep them
          from ever lining up into an obvious shape. */}
      <div className="absolute -left-[10%] -top-[20%] h-[45rem] w-[45rem] rounded-full bg-[radial-gradient(circle,rgb(var(--accent)/0.22),transparent_65%)] blur-3xl animate-drift" />
      <div
        className="absolute -right-[15%] top-[5%] h-[38rem] w-[38rem] rounded-full bg-[radial-gradient(circle,rgb(var(--info)/0.18),transparent_65%)] blur-3xl animate-drift"
        style={{ animationDelay: "-7s", animationDuration: "26s" }}
      />
      <div
        className="absolute left-[25%] top-[45%] h-[40rem] w-[40rem] rounded-full bg-[radial-gradient(circle,rgb(var(--ok)/0.12),transparent_65%)] blur-3xl animate-drift"
        style={{ animationDelay: "-14s", animationDuration: "30s" }}
      />

      {/* The floor. Laid flat in 3D and panned toward the viewer, so the page
          sits in a space rather than on a surface. Suppressed on data-dense
          app pages where it would sit behind tables. */}
      {floor ? (
        <div className="scene absolute inset-x-0 bottom-0 h-[55vh]">
          <div className="grid-floor depth h-full w-full" />
        </div>
      ) : null}

      {/* Grain. Breaks up the gradient banding that large blurred blobs cause
          on 8-bit displays. */}
      <div className="absolute inset-0 opacity-[0.15] mix-blend-overlay [background-image:url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22120%22 height=%22120%22><filter id=%22n%22><feTurbulence type=%22fractalNoise%22 baseFrequency=%220.85%22 numOctaves=%224%22/></filter><rect width=%22120%22 height=%22120%22 filter=%22url(%23n)%22 opacity=%220.5%22/></svg>')]" />

      {/* Settles the top of the page back to the canvas colour so the header
          keeps its contrast. */}
      <div className="absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-canvas to-transparent" />
    </div>
  );
}
