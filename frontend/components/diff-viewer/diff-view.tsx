"use client";

import { FileDiff, Minus, Plus } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

type LineKind = "add" | "del" | "context" | "meta" | "hunk";

interface DiffLine {
  kind: LineKind;
  text: string;
  oldNumber?: number;
  newNumber?: number;
}

interface DiffFile {
  path: string;
  lines: DiffLine[];
  added: number;
  removed: number;
}

const HUNK = /^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@/;

/** Parse a unified diff into per-file line models with real line numbers. */
export function parseUnifiedDiff(diff: string): DiffFile[] {
  const files: DiffFile[] = [];
  let current: DiffFile | null = null;
  let oldLine = 0;
  let newLine = 0;

  for (const raw of (diff ?? "").split("\n")) {
    if (raw.startsWith("--- ")) continue;
    if (raw.startsWith("+++ ")) {
      const path = raw.slice(4).replace(/^b\//, "").trim();
      current = { path, lines: [], added: 0, removed: 0 };
      files.push(current);
      continue;
    }
    if (!current) continue;

    const hunk = HUNK.exec(raw);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      current.lines.push({ kind: "hunk", text: raw });
      continue;
    }
    if (raw.startsWith("+")) {
      current.lines.push({ kind: "add", text: raw.slice(1), newNumber: newLine++ });
      current.added += 1;
    } else if (raw.startsWith("-")) {
      current.lines.push({ kind: "del", text: raw.slice(1), oldNumber: oldLine++ });
      current.removed += 1;
    } else if (raw.startsWith("\\")) {
      current.lines.push({ kind: "meta", text: raw });
    } else {
      current.lines.push({
        kind: "context",
        text: raw.startsWith(" ") ? raw.slice(1) : raw,
        oldNumber: oldLine++,
        newNumber: newLine++,
      });
    }
  }
  return files.filter((file) => file.lines.length > 0);
}

export function DiffView({
  diff,
  className,
  emptyMessage = "No changes to show.",
}: {
  diff?: string | null;
  className?: string;
  emptyMessage?: string;
}) {
  const files = React.useMemo(() => parseUnifiedDiff(diff ?? ""), [diff]);

  if (!diff || files.length === 0) {
    return (
      <EmptyState
        icon={<FileDiff className="h-7 w-7" />}
        title="No diff"
        description={emptyMessage}
      />
    );
  }

  return (
    <div className={cn("space-y-3", className)}>
      {files.map((file) => (
        <div key={file.path} className="overflow-hidden rounded-md border border-line">
          <div className="flex items-center justify-between gap-3 border-b border-line bg-elevated px-3 py-2">
            <span className="mono truncate text-xs text-ink">{file.path}</span>
            <span className="flex shrink-0 items-center gap-2 text-2xs">
              <span className="flex items-center gap-0.5 text-ok">
                <Plus className="h-3 w-3" aria-hidden />
                {file.added}
              </span>
              <span className="flex items-center gap-0.5 text-danger">
                <Minus className="h-3 w-3" aria-hidden />
                {file.removed}
              </span>
            </span>
          </div>
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full border-collapse">
              <tbody className="mono text-xs">
                {file.lines.map((line, index) => (
                  <tr
                    key={index}
                    className={cn(
                      line.kind === "add" && "diff-line-add",
                      line.kind === "del" && "diff-line-del",
                      line.kind === "hunk" && "diff-line-hunk",
                      line.kind === "meta" && "diff-line-meta",
                    )}
                  >
                    <td className="w-11 select-none border-r border-line/60 px-2 text-right align-top text-faint">
                      {line.oldNumber ?? ""}
                    </td>
                    <td className="w-11 select-none border-r border-line/60 px-2 text-right align-top text-faint">
                      {line.newNumber ?? ""}
                    </td>
                    <td className="w-5 select-none px-1 text-center align-top text-faint">
                      {line.kind === "add" ? "+" : line.kind === "del" ? "-" : ""}
                    </td>
                    <td className="whitespace-pre px-2 align-top">
                      {line.text || " "}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}

export function DiffStats({ diff }: { diff?: string | null }) {
  const files = React.useMemo(() => parseUnifiedDiff(diff ?? ""), [diff]);
  const added = files.reduce((sum, file) => sum + file.added, 0);
  const removed = files.reduce((sum, file) => sum + file.removed, 0);
  if (!files.length) return null;
  return (
    <span className="flex items-center gap-2 text-2xs">
      <span className="text-muted">
        {files.length} file{files.length === 1 ? "" : "s"}
      </span>
      <span className="text-ok">+{added}</span>
      <span className="text-danger">−{removed}</span>
    </span>
  );
}
