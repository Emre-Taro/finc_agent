"use client";

import { useCallback, useEffect, useState } from "react";
import { api, waitForRun, type Company, type CompanyScore, type Taxonomy } from "@/lib/api";
import { Bar } from "@/components/Score";
import { TickerSearch } from "@/components/TickerSearch";

export default function CompaniesPage() {
  const [tax, setTax] = useState<Taxonomy | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [form, setForm] = useState({ ticker: "", name: "", sector: "" });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => setCompanies(await api<Company[]>("/api/companies")), []);

  useEffect(() => {
    api<Taxonomy>("/api/taxonomy").then(setTax).catch((e) => setError(String(e)));
    load().catch((e) => setError(String(e)));
  }, [load]);

  async function guarded(name: string, fn: () => Promise<unknown>) {
    setBusy(name);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  const add = () =>
    guarded("add", async () => {
      await api("/api/companies", { method: "POST", body: JSON.stringify(form) });
      setForm({ ticker: "", name: "", sector: "" });
    });

  const scoreAll = () =>
    guarded("all", async () => {
      const { run_id } = await api<{ run_id: string }>("/api/companies/score-all", { method: "POST" });
      const run = await waitForRun(run_id);
      const errs = (run.stats.errors ?? {}) as Record<string, string>;
      if (Object.keys(errs).length) setError(`採点失敗: ${Object.keys(errs).join(", ")}`);
    });

  const sorted = [...companies].sort((a, b) => (b.latest_score?.total_score ?? -1) - (a.latest_score?.total_score ?? -1));
  const w = tax?.score_weights;

  return (
    <>
      <section className="panel">
        <h2>銘柄を追加</h2>
        <TickerSearch
          onSelect={(c) => setForm({ ticker: c.symbol, name: c.name, sector: c.sector ?? "" })}
        />
        <div className="row" style={{ marginTop: 8 }}>
          <input placeholder="ティッカー (例: 7203.T, AAPL)" value={form.ticker} onChange={(e) => setForm({ ...form, ticker: e.target.value })} />
          <input placeholder="企業名" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select value={form.sector} onChange={(e) => setForm({ ...form, sector: e.target.value })}>
            <option value="">セクターを選択</option>
            {tax && Object.entries(tax.sectors).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <button disabled={!!busy || !form.ticker || !form.name || !form.sector} onClick={add}>追加</button>
        </div>
        <p className="small muted">
          検索して候補を選ぶと、ティッカー・企業名・セクターが自動で入ります（セクターは業種からの推定なので、必要なら変更してください）。
          日本株は「トヨタ」「7203」、米国株は「nvidia」「AAPL」のように検索できます。
        </p>
      </section>

      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>銘柄スコア（各100点満点）</h2>
          <button className="primary" disabled={!!busy || companies.length === 0} onClick={scoreAll}>
            {busy === "all" ? "採点中…" : "全銘柄をAIで採点"}
          </button>
        </div>
        {w && (
          <p className="small muted">
            総合 = マクロ×{w.macro} + 業界×{w.industry} + 個別×{w.ticker}。50点が中立。
          </p>
        )}
        {error && <p className="error small">{error}</p>}
        <table>
          <thead>
            <tr>
              <th>銘柄</th>
              <th>総合</th>
              <th>マクロ</th>
              <th>業界</th>
              <th>個別</th>
              <th className="hide-sm">採点日時</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((c) => (
              <CompanyRow
                key={c.ticker}
                c={c}
                sectorName={tax?.sectors[c.sector] ?? c.sector}
                busy={busy}
                onScore={() => guarded(c.ticker, () => api(`/api/companies/${encodeURIComponent(c.ticker)}/score`, { method: "POST" }))}
                onDelete={() => guarded(c.ticker, () => api(`/api/companies/${encodeURIComponent(c.ticker)}`, { method: "DELETE" }))}
              />
            ))}
          </tbody>
        </table>
        {companies.length === 0 && <p className="muted small">銘柄が登録されていません。</p>}
      </section>
    </>
  );
}

function Axis({ v }: { v: number | undefined }) {
  if (v === undefined) return <span className="muted">-</span>;
  return (
    <div>
      <div>{Number(v).toFixed(0)}</div>
      <Bar value={Number(v)} />
    </div>
  );
}

function CompanyRow({ c, sectorName, busy, onScore, onDelete }: {
  c: Company; sectorName: string; busy: string | null; onScore: () => void; onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const s: CompanyScore | null = c.latest_score;
  return (
    <>
      <tr>
        <td>
          <b>{c.ticker}</b> {c.name}
          <div className="small muted">{sectorName}</div>
        </td>
        <td className="big">{s ? Number(s.total_score).toFixed(1) : "-"}</td>
        <td><Axis v={s?.macro_score} /></td>
        <td><Axis v={s?.industry_score} /></td>
        <td><Axis v={s?.ticker_score} /></td>
        <td className="small muted hide-sm">{s ? new Date(s.scored_at).toLocaleString("ja-JP") : "-"}</td>
        <td>
          <div className="row">
            <button disabled={!!busy} onClick={onScore}>{busy === c.ticker ? "採点中…" : "採点"}</button>
            {s && <button onClick={() => setOpen(!open)}>{open ? "閉じる" : "根拠"}</button>}
            <button disabled={!!busy} onClick={onDelete}>削除</button>
          </div>
        </td>
      </tr>
      {open && s && (
        <tr>
          <td colSpan={7}>
            <p><b>総評:</b> {s.summary}</p>
            <p><b>マクロ ({s.macro_score}):</b> {s.macro_reason}</p>
            <p><b>業界 ({s.industry_score}):</b> {s.industry_reason}</p>
            <p><b>個別 ({s.ticker_score}):</b> {s.ticker_reason}</p>
            <p className="small muted">
              定量ベースライン: マクロ {s.evidence.baseline.macro ?? "-"} / 業界 {s.evidence.baseline.industry ?? "-"} / 個別 {s.evidence.baseline.ticker ?? "-"}
              （材料: マクロ記事 {s.evidence.counts.macro_news}件, 業界 {s.evidence.counts.sector_impacts}件, 個別 {s.evidence.counts.ticker_impacts}件）
            </p>
          </td>
        </tr>
      )}
    </>
  );
}
