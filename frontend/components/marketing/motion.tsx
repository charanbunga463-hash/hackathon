"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Motion primitives for the public pages.
 *
 * Two rules hold everywhere in here:
 *
 *   * Only `transform` and `opacity` are animated, so every effect stays on the
 *     compositor and never triggers layout.
 *   * `prefers-reduced-motion` is honoured by falling back to the settled
 *     state, not by freezing an element mid-animation. Someone who asks for
 *     less motion still sees the finished page, just without the travel.
 */

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/* --------------------------------------------------------------- reveal --- */

/**
 * Fades and lifts its children the first time they scroll into view. One-shot:
 * the observer disconnects after firing, so scrolling back up does not replay.
 */
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    if (prefersReducedMotion()) {
      setShown(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          observer.disconnect();
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={cn("reveal", shown && "reveal-in", className)}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}

/* ----------------------------------------------------------------- tilt --- */

/**
 * A restrained tilt toward the pointer, with a pale highlight that tracks the
 * cursor. Small angles on purpose: on a bright, paper-like surface a large
 * rotation reads as a gimmick, a two-degree one reads as light moving.
 *
 * Pointer maths runs through `requestAnimationFrame` so a fast mouse cannot
 * queue more style writes than the display can show.
 */
export function Tilt({
  children,
  className,
  strength = 5,
  glare = true,
}: {
  children: React.ReactNode;
  className?: string;
  strength?: number;
  glare?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node || prefersReducedMotion()) return;

    // Coarse pointers have no hover state to track; a tap should not leave the
    // card stuck at an angle.
    if (window.matchMedia("(pointer: coarse)").matches) return;

    const apply = (event: PointerEvent) => {
      if (frame.current !== null) return;
      frame.current = requestAnimationFrame(() => {
        frame.current = null;
        const rect = node.getBoundingClientRect();
        const px = (event.clientX - rect.left) / rect.width;
        const py = (event.clientY - rect.top) / rect.height;
        node.style.setProperty("--rx", `${(0.5 - py) * strength}deg`);
        node.style.setProperty("--ry", `${(px - 0.5) * strength}deg`);
        node.style.setProperty("--mx", `${px * 100}%`);
        node.style.setProperty("--my", `${py * 100}%`);
      });
    };

    const reset = () => {
      if (frame.current !== null) {
        cancelAnimationFrame(frame.current);
        frame.current = null;
      }
      node.style.setProperty("--rx", "0deg");
      node.style.setProperty("--ry", "0deg");
    };

    node.addEventListener("pointermove", apply);
    node.addEventListener("pointerleave", reset);
    return () => {
      node.removeEventListener("pointermove", apply);
      node.removeEventListener("pointerleave", reset);
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    };
  }, [strength]);

  return (
    <div style={{ perspective: "1000px" }}>
      <div
        ref={ref}
        className={cn(
          "relative transition-transform duration-300 ease-out",
          "[transform:rotateX(var(--rx,0deg))_rotateY(var(--ry,0deg))]",
          "motion-reduce:!transform-none",
          className,
        )}
      >
        {children}
        {glare ? (
          <span
            aria-hidden
            className="pointer-events-none absolute inset-0 rounded-[inherit] opacity-0 transition-opacity duration-300 [background:radial-gradient(320px_circle_at_var(--mx,50%)_var(--my,50%),rgb(var(--brand)/0.1),transparent_62%)] group-hover:opacity-100"
          />
        ) : null}
      </div>
    </div>
  );
}
