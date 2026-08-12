"use client";

import { ChevronDown, ChevronRight, File, FileCode2, Folder } from "lucide-react";
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
    <div className={cn("scroll-thin overflow-y-auto p-1.5", className)}>
      {nodes.map((node) => (
        <TreeNode key={node.path} node={node} depth={0} selected={selected} onSelect={onSelect} />
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
          className="flex w-full items-center gap-1 rounded px-1.5 py-1 text-left text-xs text-muted hover:bg-elevated hover:text-ink"
          style={{ paddingLeft: `${depth * 12 + 6}px` }}
        >
          {open ? (
            <ChevronDown className="h-3 w-3 shrink-0" aria-hidden />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0" aria-hidden />
          )}
          <Folder className="h-3.5 w-3.5 shrink-0 text-faint" aria-hidden />
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
  return (
    <button
      onClick={() => onSelect(node.path)}
      className={cn(
        "flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-xs",
        selected === node.path
          ? "bg-accent/15 text-accent"
          : "text-muted hover:bg-elevated hover:text-ink",
      )}
      style={{ paddingLeft: `${depth * 12 + 20}px` }}
      title={`${node.path} · ${formatBytes(node.size)}`}
    >
      {isPython ? (
        <FileCode2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
      ) : (
        <File className="h-3.5 w-3.5 shrink-0 text-faint" aria-hidden />
      )}
      <span className="truncate">{node.name}</span>
    </button>
  );
}

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
        <Spinner />
      </div>
    );
  }
  if (!file) {
    return (
      <div className={cn("flex items-center justify-center py-16 text-xs text-muted", className)}>
        Select a file to view its source.
      </div>
    );
  }

  const lines = file.content.split("\n");
  let firstHighlight = true;

  return (
    <div className={cn("scroll-thin overflow-auto", className)}>
      <table className="w-full border-collapse">
        <tbody className="mono text-xs">
          {lines.map((line, index) => {
            const number = index + 1;
            const isHit = highlight.has(number);
            const ref = isHit && firstHighlight ? focusRef : undefined;
            if (isHit) firstHighlight = false;
            return (
              <tr
                key={number}
                ref={ref}
                className={cn(isHit && "bg-danger/12 outline outline-1 outline-danger/30")}
              >
                <td className="w-12 select-none border-r border-line/60 px-2 text-right align-top text-faint">
                  {number}
                </td>
                <td className="whitespace-pre px-3 align-top text-ink">{line || " "}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {file.truncated ? (
        <p className="border-t border-line px-3 py-2 text-2xs text-muted">
          File truncated for display ({formatBytes(file.size)} total).
        </p>
      ) : null}
    </div>
  );
}
