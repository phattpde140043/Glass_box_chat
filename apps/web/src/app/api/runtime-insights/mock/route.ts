import { NextResponse } from "next/server";
import { buildRuntimeInsightFixtureBySession } from "@/features/runtime-insights/fixtures/runtime-insight-fixtures";
import { buildRuntimeInsightSummary } from "@/features/runtime-insights/services/runtime-insight-report";

export async function GET() {
  const eventsBySession = buildRuntimeInsightFixtureBySession();
  const summary = buildRuntimeInsightSummary(eventsBySession);

  return NextResponse.json({
    status: "ok",
    summary,
  });
}
