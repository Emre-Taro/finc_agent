"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api, waitForRun,
  type ImpactSummary, type Indicator, type NewsDetail, type NewsItem, type Run, type Taxonomy,
} from "@/lib/api";
import { Direction, ScoreChip, Sparkline } from "@/components/Score";
import { IndicatorModal } from "@/components/IndicatorModal";

const SOURCES = ["Bloomberg", "Reuters", "Financial Times", "日本経済新聞"];
const PAGE = 50;

function fmtDate(s: string | null) {
  return s ? new Date(s).toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-";
}

function runLabel(r: Run) {
  const s = r.stats as Record<string, number>;
  if (r.status === "running") return "実行中…";
  if (r.status === "failed") return `失敗: ${r.error ?? ""}`;
  return `新規 ${s.inserted ?? 0}件 / 既存スキップ ${s.already_stored ?? 0}件 / 評価 ${s.analyzed ?? 0}件 / 評価失敗 ${s.analysis_failed ?? 0}件`;
}

export default function Dashboard() {
  const [tax, setTax] = useState<Taxonomy | null>(null);
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [openIndicator, setOpenIndicator] = useState<Indicator | null>(null);
  const [summary, setSummary] = useState<ImpactSummary[]>([]);
  const [summaryDays, setSummaryDays] = useState(7);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [source, setSource] = useState("");
  const [sector, setSector] = useState("");
  const [q, setQ] = useState("");
  const [lastRun, setLastRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadNews = useCallback(async () => {
    const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (source) params.set("source", source);
    if (sector) params.set("sector", sector);
    if (q) params.set("q", q);
    const res = await api<{ items: NewsItem[]; total: number }>(`/api/news?${params}`);
    setNews(res.items);
    setTotal(res.total);
  }, [offset, source, sector, q]);

  const loadSummary = useCallback(async () => {
    setSummary(await api<ImpactSummary[]>(`/api/impacts/summary?days=${summaryDays}`));
  }, [summaryDays]);

  const loadIndicators = useCallback(async () => setIndicators(await api<Indicator[]>("/api/indicators?history_days=180")), []);

  useEffect(() => {
    api<Taxonomy>("/api/taxonomy").then(setTax).catch((e) => setError(String(e)));
    api<Run[]>("/api/runs?kind=news&limit=1").then((r) => setLastRun(r[0] ?? null)).catch(() => {});
    loadIndicators().catch((e) => setError(String(e)));
  }, [loadIndicators]);
  useEffect(() => { loadNews().catch((e) => setError(String(e))); }, [loadNews]);
  useEffect(() => { loadSummary().catch((e) => setError(String(e))); }, [loadSummary]);

  async function runJob(name: string, path: string) {
    setBusy(name);
    setError(null);
    try {
      const { run_id } = await api<{ run_id: string }>(path, { method: "POST" });
      await waitForRun(run_id, setLastRun);
      await Promise.all([loadNews(), loadSummary()]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function refreshIndicators() {
    setBusy("indicators");
    setError(null);
    try {
      const stats = await api<{ errors: Record<string, string> }>("/api/indicators/refresh", { method: "POST" });
      const errs = Object.keys(stats.errors);
      if (errs.length) setError(`取得失敗: ${errs.join(", ")}`);
      await loadIndicators();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  const closeIndicator = useCallback(() => setOpenIndicator(null), []);

  const sectorSummary = summary.filter((s) => s.target_type === "sector").sort((a, b) => b.avg_score - a.avg_score);
  const indicatorSummary = summary.filter((s) => s.target_type === "indicator").sort((a, b) => b.avg_score - a.avg_score);

  return (
    <>
      <section className="panel">
        <div className="row">
          <button className="primary" disabled={!!busy} onClick={() => runJob("news", "/api/ingest/news")}>
            {busy === "news" ? "取得・評価中…" : "ニュースを取得してAI評価"}
          </button>
          <button disabled={!!busy} onClick={() => runJob("reanalyze", "/api/news/reanalyze")}>
            {busy === "reanalyze" ? "再評価中…" : "失敗・未評価を再評価"}
          </button>
          <button disabled={!!busy} onClick={refreshIndicators}>
            {busy === "indicators" ? "更新中…" : "金融指標を更新"}
          </button>
        </div>
        {lastRun && (
          <p className="small muted">
            前回のニュース取得: {fmtDate(lastRun.started_at)} — {runLabel(lastRun)}
          </p>
        )}
        {error && <p className="error small">{error}</p>}
      </section>

      <section className="panel">
        <h2>金融指標</h2>
        <div className="grid">
          {indicators.map((i) => (
            <div
              className="card clickable"
              key={i.code}
              role="button"
              tabIndex={0}
              title="クリックで詳しく見る"
              onClick={() => setOpenIndicator(i)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setOpenIndicator(i))}
            >
              <div className="small muted">{i.name}</div>
              <div className="value">
                {i.latest === null ? "-" : i.latest.toLocaleString("ja-JP", { maximumFractionDigits: 2 })}
                <span className="small muted"> {i.unit}</span>
              </div>
              <div className="small">
                {i.change === null ? "" : `${i.change >= 0 ? "+" : ""}${i.change.toFixed(2)}`}
                <span className="muted"> {i.latest_date ?? ""}</span>
              </div>
              <Sparkline values={i.history.map((h) => h.value)} />
            </div>
          ))}
        </div>
        {indicators.every((i) => i.latest === null) && <p className="muted small">「金融指標を更新」を押してデータを取得してください。</p>}
        {openIndicator && <IndicatorModal indicator={openIndicator} onClose={closeIndicator} />}
      </section>

      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>ニュースの影響（直近{summaryDays}日の平均）</h2>
          <select value={summaryDays} onChange={(e) => setSummaryDays(Number(e.target.value))}>
            {[1, 3, 7, 14, 30].map((d) => <option key={d} value={d}>{d}日</option>)}
          </select>
        </div>
        <div className="detail" style={{ marginTop: 0 }}>
          <div>
            <div className="small muted">業界（+ = 好材料）</div>
            <table>
              <tbody>
                {sectorSummary.map((s) => (
                  <tr key={s.target_code}>
                    <td>{tax?.sectors[s.target_code] ?? s.target_code}</td>
                    <td><ScoreChip score={Number(s.avg_score)} /></td>
                    <td className="small muted">{s.nonzero_count}/{s.news_count}件が言及</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <div className="small muted">指標（▲ = 上昇圧力）</div>
            <table>
              <tbody>
                {indicatorSummary.map((s) => (
                  <tr key={s.target_code}>
                    <td>{tax?.indicators[s.target_code] ?? s.target_code}</td>
                    <td><Direction score={Number(s.avg_score)} /></td>
                    <td className="small muted">{s.nonzero_count}/{s.news_count}件が言及</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        {summary.length === 0 && <p className="muted small">評価済みのニュースがありません。</p>}
      </section>

      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>ニュース（{total}件）</h2>
          <div className="row">
            <input placeholder="タイトル検索" value={q} onChange={(e) => { setOffset(0); setQ(e.target.value); }} />
            <select value={source} onChange={(e) => { setOffset(0); setSource(e.target.value); }}>
              <option value="">全媒体</option>
              {SOURCES.map((s) => <option key={s}>{s}</option>)}
            </select>
            <select value={sector} onChange={(e) => { setOffset(0); setSector(e.target.value); }}>
              <option value="">全業界</option>
              {tax && Object.entries(tax.sectors).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
        </div>
        {news.map((n) => <NewsRow key={n.id} item={n} tax={tax} />)}
        <div className="row" style={{ marginTop: 12 }}>
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>前へ</button>
          <span className="small muted">{total ? `${offset + 1}–${Math.min(offset + PAGE, total)}` : "0"} / {total}</span>
          <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>次へ</button>
        </div>
      </section>
    </>
  );
}

function NewsRow({ item, tax }: { item: NewsItem; tax: Taxonomy | null }) {
  const [detail, setDetail] = useState<NewsDetail | null>(null);
  const [open, setOpen] = useState(false);

  async function toggle() {
    if (!open && !detail) setDetail(await api<NewsDetail>(`/api/news/${item.id}`));
    setOpen(!open);
  }

  const impacts = detail?.news_impacts ?? [];
  const byType = (t: string) => impacts.filter((i) => i.target_type === t).sort((a, b) => Math.abs(b.score) - Math.abs(a.score));

  return (
    <div className="news-item">
      <div className="row small muted">
        <span>{fmtDate(item.published_at)}</span>
        <span>{item.source}</span>
        {item.analysis_status !== "done" && <span className="error">[{item.analysis_status === "failed" ? "評価失敗" : "未評価"}]</span>}
      </div>
      <div className="title"><a href={item.url} target="_blank" rel="noreferrer">{item.title}</a></div>
      {item.analysis_status === "done" && (
        <>
          <div className="row" style={{ margin: "6px 0" }}>
            <ScoreChip label="マクロ" score={item.macro_score} />
            <ScoreChip label={`業界:${tax?.sectors[item.primary_sector ?? ""] ?? "-"}`} score={item.industry_score} />
            <ScoreChip label={`銘柄:${item.primary_ticker ?? "-"}`} score={item.primary_ticker ? item.ticker_score : null} />
            <button className="small" onClick={toggle}>{open ? "閉じる" : "影響をすべて見る"}</button>
          </div>
          <div>{item.content_summary}</div>
        </>
      )}
      {open && detail && (
        <>
          <p className="small"><b>AIの解説:</b> {detail.ai_analysis_reason}</p>
          <div className="detail">
            <ImpactTable title="業界への影響" rows={byType("sector")} />
            <ImpactTable title="指標への影響（方向）" rows={byType("indicator")} direction />
            {byType("ticker").length > 0 && <ImpactTable title="個別銘柄への影響" rows={byType("ticker")} showCode />}
          </div>
        </>
      )}
    </div>
  );
}

function ImpactTable({ title, rows, direction, showCode }: { title: string; rows: NewsDetail["news_impacts"]; direction?: boolean; showCode?: boolean }) {
  return (
    <div>
      <div className="small muted">{title}</div>
      <table>
        <tbody>
          {rows.map((r) => (
            <tr key={r.target_code}>
              <td style={{ whiteSpace: "nowrap" }}>{showCode ? `${r.target_code} ${r.target_name ?? ""}` : r.target_name}</td>
              <td style={{ whiteSpace: "nowrap" }}>{direction ? <Direction score={Number(r.score)} /> : <ScoreChip score={Number(r.score)} />}</td>
              <td className="small muted">{r.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
