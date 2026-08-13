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
import { ErrorNote, LinkButton, Spinner } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useEvents";
import { getReport, reportMarkdownUrl } from "@/lib/api";

export default function ReportPage() {
  const params = useParams<{ id: string }>();
  const { data: report, error, loading } = useAsync(() => getReport(params.id), [params.id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2.5 py-24">
        <Spinner className="h-5 w-5" />
        <span className="text-sm text-muted">Loading report…</span>
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
    <div className="space-y-5 animate-fade-up">
      <BackLink projectId={report.project_id} />

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="eyebrow">Investigation</p>
          <h1 className="mt-1.5 text-2xl font-bold tracking-tight text-ink">
            {report.project_name}
          </h1>
          <p className="mt-1 text-xs text-muted">
            Session <span className="mono">{report.session_id}</span>
          </p>
        </div>
        <LinkButton href={reportMarkdownUrl(report.session_id)} download variant="secondary">
          <Download className="h-4 w-4" /> Download Markdown
        </LinkButton>
      </header>

      <VerdictBanner
        verified={report.verified}
        headline={report.headline}
        detail={report.disclaimer}
      />

      <ReportProvenance report={report} />

      <div className="grid gap-5 xl:grid-cols-[1fr_20rem]">
        <div className="min-w-0">
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
      className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted transition-colors hover:text-brand-ink"
    >
      <ArrowLeft className="h-3.5 w-3.5" /> {projectId ? "Back to project" : "Projects"}
    </Link>
  );
}
