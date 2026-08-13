"use client";

import { ChevronDown, ChevronRight, File, FileCode2, Folder, FolderOpen } from "lucide-react";
import * as React from "react";

import { Spinner } from "@/components/ui/primitives";
import { cn, formatBytes } from "@/lib/utils";
import type { FileContent, FileNode } from "@/types";

export function FileTree({
  nodes,
  selected,
  onSelect,
  className,
}: {
  nodes: FileNode[];
  selected?: string | null;
  onSelect: (path: string) => void;
  className?: string;
}) {
  return (
    <div className={cn("scroll-thin overflow-y-auto bg-sunken p-2", className)}>
      {nodes.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          depth={0}
          selected={selected}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

function TreeNode({
  node,
  depth,
  selected,
  onSelect,
}: {
  node: FileNode;
  depth: number;
  selected?: string | null;
  onSelect: (path: string) => void;
}) {
  // Top two levels start expanded: deep trees are noise, shallow ones are context.
  const [open, setOpen] = React.useState(depth < 2);

  if (node.type === "directory") {
    return (
      <div>
        <button
          onClick={() => setOpen((value) => !value)}
          className="flex w-full items-center gap-1 rounded-lg px-1.5 py-1 text-left text-xs font-medium text-muted transition-colors hover:bg-surface hover:text-ink"
          style={{ paddingLeft: `${depth * 12 + 6}px` }}
        >
          {open ? (
            <ChevronDown className="h-3 w-3 shrink-0" aria-hidden />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0" aria-hidden />
          )}
          {open ? (
            <FolderOpen className="h-3.5 w-3.5 shrink-0 text-brand" aria-hidden />
          ) : (
            <Folder className="h-3.5 w-3.5 shrink-0 text-faint" aria-hidden />
          )}
          <span className="truncate">{node.name}</span>
        </button>
        {open
          ? (node.children ?? []).map((child) => (
              <TreeNode
                key={child.path}
                node={child}
                depth={depth + 1}
                selected={selected}
                onSelect={onSelect}
              />
            ))
          : null}
      </div>
    );
  }

  const isPython = node.name.endsWith(".py");
  const active = selected === node.path;
  return (
    <button
      onClick={() => onSelect(node.path)}
      className={cn(
        "flex w-full items-center gap-1.5 rounded-lg px-1.5 py-1 text-left text-xs transition-colors",
        active
          ? "bg-brand-soft font-semibold text-brand-ink ring-1 ring-brand-line"
          : "text-muted hover:bg-surface hover:text-ink",
      )}
      style={{ paddingLeft: `${depth * 12 + 20}px` }}
      title={`${node.path} · ${formatBytes(node.size)}`}
    >
      {isPython ? (
        <FileCode2
          className={cn("h-3.5 w-3.5 shrink-0", active ? "text-brand" : "text-info")}
          aria-hidden
        />
      ) : (
        <File className="h-3.5 w-3.5 shrink-0 text-faint" aria-hidden />
      )}
      <span className="truncate">{node.name}</span>
    </button>
  );
}

/**
 * A read-only source view.
 *
 * Line numbers sit in their own gutter column so a copy-paste of the code does
 * not drag the numbers along with it, and a highlighted line is tinted rather
 * than inverted so the code stays legible.
 */
export function CodeView({
  file,
  loading,
  highlightLines = [],
  className,
}: {
  file?: FileContent | null;
  loading?: boolean;
  highlightLines?: number[];
  className?: string;
}) {
  const highlight = React.useMemo(() => new Set(highlightLines), [highlightLines]);
  const focusRef = React.useRef<HTMLTableRowElement | null>(null);

  React.useEffect(() => {
    focusRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [file?.path, highlightLines.join(",")]);

  if (loading) {
    return (
      <div className={cn("flex items-center justify-center py-16", className)}>
        <Spinner className="h-5 w-5" />
      </div>
    );
  }
  if (!file) {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-center gap-2 py-16 text-center",
          className,
        )}
      >
        <FileCode2 className="h-6 w-6 text-faint" aria-hidden />
        <p className="text-xs text-muted">Select a file to view its source.</p>
      </div>
    );
  }

  const lines = file.content.split("\n");
  let firstHighlight = true;

  return (
    <div className={cn("scroll-thin overflow-auto bg-surface", className)}>
      <table className="w-full border-collapse">
        <tbody className="mono text-xs">
          {lines.map((line, index) => {
            const number = index + 1;
            const isHit = highlight.has(number);
            const ref = isHit && firstHighlight ? focusRef : undefined;
            if (isHit) firstHighlight = false;
            return (
              <tr key={number} className={cn(isHit && "bg-danger-soft")}>
                <td
                  className={cn(
                    "w-12 select-none border-r px-2 text-right align-top text-2xs",
                    isHit
                      ? "border-danger-line bg-danger/10 font-bold text-danger-ink"
                      : "border-line text-faint",
                  )}
                >
                  {number}
                </td>
                <td className="whitespace-pre px-3 align-top leading-relaxed text-ink">
                  {line || " "}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {file.truncated ? (
        <p className="border-t border-line bg-warn-soft px-3 py-2 text-2xs font-medium text-warn-ink">
          File truncated for display ({formatBytes(file.size)} total).
        </p>
      ) : null}
    </div>
  );
}
