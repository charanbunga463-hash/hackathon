"use client";

import { ArrowLeft, Download } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import {
  InvestigationReportBody,
  ReportProvenance,
  ReportTimeline,
} from "@/components/reports/investigation-report";
import { VerdictBanner } from "@/components/ui/claim-ladder";
import { Button, ErrorNote, Spinner } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useEvents";
import { getReport, reportMarkdownUrl } from "@/lib/api";

export default function ReportPage() {
  const params = useParams<{ id: string }>();
  const { data: report, error, loading } = useAsync(() => getReport(params.id), [params.id]);

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }
  if (error || !report) {
    return (
      <div className="space-y-4">
        <BackLink projectId={null} />
        <ErrorNote message={error ?? "Report not found."} />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <BackLink projectId={report.project_id} />

      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-ink">
            Investigation report
          </h1>
          <p className="text-sm text-muted">
            {report.project_name} · session{" "}
            <span className="mono text-xs">{report.session_id}</span>
          </p>
        </div>
        <a href={reportMarkdownUrl(report.session_id)} download>
          <Button size="sm" variant="secondary">
            <Download className="h-3.5 w-3.5" /> Download Markdown
          </Button>
        </a>
      </header>

      <VerdictBanner
        verified={report.verified}
        headline={report.headline}
        detail={report.disclaimer}
      />

      <ReportProvenance report={report} />

      <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
        <div className="min-w-0 space-y-4">
          <InvestigationReportBody report={report} />
        </div>
        <ReportTimeline report={report} />
      </div>
    </div>
  );
}

function BackLink({ projectId }: { projectId?: string | null }) {
  // A report belongs to a project, so "back" returns to that project's own
  // history rather than to a global list that no longer exists.
  return (
    <Link
      href={projectId ? `/projects/${projectId}` : "/projects"}
      className="inline-flex items-center gap-1 text-xs text-muted hover:text-ink"
    >
      <ArrowLeft className="h-3 w-3" /> {projectId ? "Back to project" : "Projects"}
    </Link>
  );
}
