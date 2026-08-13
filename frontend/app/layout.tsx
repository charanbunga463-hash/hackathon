import type { Metadata, Viewport } from "next";

import { ChunkRecovery } from "@/components/system/chunk-recovery";

import "./globals.css";

export const metadata: Metadata = {
  title: "API Doctor — Detect. Diagnose. Repair. Verify.",
  description:
    "An AI agent that detects broken APIs, investigates the root cause against real source and test output, proposes a minimal patch, and verifies the repair by running the project's own tests.",
  icons: { icon: "/icon.svg" },
};

/**
 * The app ships one theme: Daylight. Declaring it here means form controls,
 * scrollbars and the browser's own UI paint light too, and a device set to
 * dark mode cannot invert the page out from under the design.
 */
export const viewport: Viewport = {
  colorScheme: "light",
  themeColor: "#ffffff",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="light" style={{ colorScheme: "light" }}>
      {/* The chrome lives in the route-group layouts: `(app)` renders the
          authenticated workspace, `(auth)` the signed-out card, `(marketing)`
          the public site. */}
      <body className="min-h-screen bg-canvas text-ink antialiased">
        {/* Recovers a tab left holding a pre-deploy route manifest. Renders
            nothing; see the note in chunk-recovery.tsx. */}
        <ChunkRecovery />
        {children}
      </body>
    </html>
  );
}
