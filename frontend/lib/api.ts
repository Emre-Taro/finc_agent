const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export type Run = {
  id: string;
  kind: string;
  started_at: string;
  finished_at: string | null;
  status: "running" | "success" | "partial" | "failed";
  stats: Record<string, unknown>;
  error: string | null;
};

/** バックグラウンドジョブが終わるまでポーリングする */
export async function waitForRun(runId: string, onTick?: (r: Run) => void): Promise<Run> {
  for (;;) {
    const run = await api<Run>(`/api/runs/${runId}`);
    onTick?.(run);
    if (run.status !== "running") return run;
    await new Promise((r) => setTimeout(r, 3000));
  }
}

export type Taxonomy = {
  sectors: Record<string, string>;
  indicators: Record<string, string>;
  score_weights: Record<string, number>;
};

export type NewsItem = {
  id: string;
  published_at: string | null;
  title: string;
  url: string;
  source: string;
  content_summary: string | null;
  macro_score: number | null;
  industry_score: number | null;
  ticker_score: number | null;
  primary_sector: string | null;
  primary_ticker: string | null;
  ai_analysis_reason: string | null;
  analysis_status: "pending" | "done" | "failed";
};

export type Impact = {
  target_type: "sector" | "indicator" | "ticker";
  target_code: string;
  target_name: string | null;
  score: number;
  reason: string | null;
};

export type NewsDetail = NewsItem & { raw_excerpt: string | null; analysis_error: string | null; news_impacts: Impact[] };

export type ImpactSummary = {
  target_type: "sector" | "indicator";
  target_code: string;
  avg_score: number;
  nonzero_count: number;
  news_count: number;
};

export type Indicator = {
  code: string;
  name: string;
  unit: string;
  latest: number | null;
  latest_date: string | null;
  change: number | null;
  history: { observed_on: string; value: number }[];
};

export type CompanyScore = {
  id: string;
  ticker: string;
  scored_at: string;
  macro_score: number;
  industry_score: number;
  ticker_score: number;
  total_score: number;
  macro_reason: string;
  industry_reason: string;
  ticker_reason: string;
  summary: string;
  evidence: { baseline: Record<string, number | null>; counts: Record<string, number> };
};

export type TickerCandidate = {
  symbol: string;
  name: string;
  exchange: string | null;
  sector: string | null; // taxonomy の GICS セクターコード。対応づけできなければ null
  sector_detail: string | null; // JPX 33業種 / Yahoo の業種
  source: "jpx" | "yahoo";
};

export type Company = { ticker: string; name: string; sector: string; latest_score: CompanyScore | null };
