/**
 * The API Doctor mark — an upward chevron "A" washed in the same blue→gold→red
 * spectrum as the hero wave, so the logo and the centerpiece share a language.
 * Kept as a tiny inline SVG (a brand glyph, not an illustration).
 */
export function MarkA({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      role="img"
      aria-label="API Doctor"
    >
      <defs>
        <linearGradient id="mark-a-grad" x1="16" y1="4" x2="16" y2="28">
          <stop offset="0" stopColor="#fb4d2f" />
          <stop offset="0.4" stopColor="#f6cb3f" />
          <stop offset="0.7" stopColor="#27d9b3" />
          <stop offset="1" stopColor="#1a8cf2" />
        </linearGradient>
      </defs>
      <path
        d="M16 4 L28 27 L21.5 27 L16 14.5 L10.5 27 L4 27 Z"
        fill="url(#mark-a-grad)"
      />
    </svg>
  );
}
