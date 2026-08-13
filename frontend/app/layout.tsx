import type { Metadata } from "next";

import { ChunkRecovery } from "@/components/system/chunk-recovery";
import { THEME_BOOTSTRAP } from "@/components/theme/theme-provider";

import "./globals.css";

export const metadata: Metadata = {
  title: "API Doctor — Detect. Diagnose. Repair. Verify.",
  description:
    "An AI agent that detects broken APIs, investigates the root cause against real source and test output, proposes a minimal patch, and verifies the repair by running the project's own tests.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/*
          Runs before first paint so the page is already in the user's chosen
          theme. The app is bright by default; this only adds the `.dark` class
          for the rare account that has explicitly opted into the dark theme,
          before React hydrates, so there is no flash.
        */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      {/* The chrome lives in the route-group layouts: `(app)` renders the
          authenticated shell, `(auth)` the signed-out card. */}
      <body className="min-h-screen bg-canvas text-ink antialiased">
        {/* Recovers a tab left holding a pre-deploy route manifest. Renders
            nothing; see the note in chunk-recovery.tsx. */}
        <ChunkRecovery />
        {children}
      </body>
    </html>
  );
}
