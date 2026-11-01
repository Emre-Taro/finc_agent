"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Indicator, type IndicatorDetail } from "@/lib/api";
import { Direction } from "@/components/Score";

// 日次データしかないので、1日・5日は「直近N営業日分の変化」として観測値の件数で切る（前日終値を起点に含める）
type Range = { label: string; days?: number; bars?: number };
const RANGES: Range[] = [
  { label: "1日", bars: 2 },
  { label: "5日", bars: 6 },
  { label: "1か月", days: 31 },
  { label: "3か月", days: 92 },
  { label: "6か月", days: 183 },
  { label: "1年", days: 366 },
];

type Point = { observed_on: string; value: number };

function fmt(v: number) {
  return v.toLocaleString("ja-JP", { maximumFractionDigits: 2 });
}

function signed(v: number, digits = 2) {
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

/** 指標カードをクリックしたときの全画面表示。長めの履歴チャートと関連ニュースを出す */
export function IndicatorModal({ indicator, onClose }: { indicator: Indicator; onClose: () => void }) {
  const [detail, setDetail] = useState<IndicatorDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<Range>(RANGES[4]);

  useEffect(() => {
    api<IndicatorDetail>(`/api/indicators/${encodeURIComponent(indicator.code)}?history_days=400`)
      .then(setDetail)
      .catch((e) => setError(String(e)));
  }, [indicator.code]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  // 詳細の読み込みが終わるまではカードが持っている180日分の履歴で描く
  const all = detail?.history ?? indicator.history;
  const points = useMemo(() => {
    if (range.bars) return all.slice(-range.bars);
    const from = new Date();
    from.setDate(from.getDate() - (range.days ?? 0));
    const cut = from.toISOString().slice(0, 10);
    return all.filter((p) => p.observed_on >= cut);
  }, [all, range]);

  const stats = useMemo(() => {
    if (points.length === 0) return null;
    const vals = points.map((p) => p.value);
    const first = vals[0];
    const last = vals[vals.length - 1];
    return {
      change: last - first,
      pct: first !== 0 ? ((last - first) / Math.abs(first)) * 100 : null,
      high: Math.max(...vals),
      low: Math.min(...vals),
      avg: vals.reduce((a, b) => a + b, 0) / vals.length,
    };
  }, [points]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={indicator.name} onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div className="muted small">{indicator.code}</div>
            <h2 style={{ margin: "2px 0 4px", fontSize: 20 }}>{indicator.name}</h2>
            <div className="row" style={{ alignItems: "baseline" }}>
              <span className="big">{indicator.latest === null ? "-" : fmt(indicator.latest)}</span>
              <span className="muted">{indicator.unit}</span>
              {indicator.change !== null && <span>前回比 {signed(indicator.change)}</span>}
              <span className="small muted">{indicator.latest_date ?? ""}</span>
            </div>
          </div>
          <button onClick={onClose} aria-label="閉じる">✕ 閉じる</button>
        </div>

        <div className="row" style={{ justifyContent: "space-between", margin: "12px 0 8px" }}>
          <div className="row">
            {RANGES.map((r) => (
              <button key={r.label} className={r === range ? "primary" : ""} onClick={() => setRange(r)}>
                {r.label}
              </button>
            ))}
          </div>
          {stats && (
            <div className="row small">
              <span>期間変化 <b>{signed(stats.change)}</b>{stats.pct !== null && ` (${signed(stats.pct)}%)`}</span>
              <span>高値 <b>{fmt(stats.high)}</b></span>
              <span>安値 <b>{fmt(stats.low)}</b></span>
              <span>平均 <b>{fmt(stats.avg)}</b></span>
            </div>
          )}
        </div>

        <div className="modal-chart">
          {points.length >= 2 ? <LineChart points={points} unit={indicator.unit} /> : <p className="muted">この期間のデータがありません。</p>}
        </div>

        <h3 style={{ fontSize: 14, margin: "16px 0 6px" }}>この指標に影響するとAIが評価したニュース（▲ = 上昇圧力）</h3>
        {error && <p className="error small">{error}</p>}
        {!detail && !error && <p className="muted small">読み込み中…</p>}
        {detail && detail.news.length === 0 && <p className="muted small">関連ニュースはまだありません。</p>}
        {detail && detail.news.length > 0 && (
          <table>
            <tbody>
              {detail.news.map((n) => (
                <tr key={n.id}>
                  <td className="small muted" style={{ whiteSpace: "nowrap" }}>
                    {n.published_at ? new Date(n.published_at).toLocaleDateString("ja-JP") : "-"}<br />{n.source}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}><Direction score={Number(n.score)} /></td>
                  <td>
                    <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a>
                    {n.reason && <div className="small muted">{n.reason}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/** min〜max を覆うきりの良い目盛りを返す */
function niceTicks(min: number, max: number, count = 5) {
  const span = max - min || Math.abs(max) || 1;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}

function LineChart({ points, unit }: { points: Point[]; unit: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 400 });
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const pad = { l: 64, r: 16, t: 12, b: 28 };
  const iw = Math.max(1, size.w - pad.l - pad.r);
  const ih = Math.max(1, size.h - pad.t - pad.b);

  const vals = points.map((p) => p.value);
  const ticks = niceTicks(Math.min(...vals), Math.max(...vals));
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const x = (i: number) => pad.l + (i / (points.length - 1)) * iw;
  const y = (v: number) => pad.t + ih - ((v - yMin) / (yMax - yMin || 1)) * ih;

  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join("");
  const area = `${path}L${x(points.length - 1)},${pad.t + ih}L${pad.l},${pad.t + ih}Z`;

  const xLabelCount = Math.max(2, Math.floor(iw / 110));
  const xIdx = Array.from(new Set(Array.from({ length: xLabelCount }, (_, k) => Math.round((k / (xLabelCount - 1)) * (points.length - 1)))));

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - rect.left - pad.l) / iw) * (points.length - 1));
    setHover(Math.max(0, Math.min(points.length - 1, i)));
  }

  const hp = hover !== null ? points[hover] : null;

  return (
    <div ref={ref} style={{ position: "relative", width: "100%", height: "100%" }}>
      <svg width={size.w} height={size.h} onPointerMove={onMove} onPointerLeave={() => setHover(null)} style={{ display: "block", touchAction: "none" }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={pad.l + iw} y1={y(t)} y2={y(t)} stroke="var(--border)" />
            <text x={pad.l - 8} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--muted)">{fmt(t)}</text>
          </g>
        ))}
        {xIdx.map((i) => (
          <text key={i} x={x(i)} y={size.h - 8} textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"} fontSize={11} fill="var(--muted)">
            {points[i].observed_on.slice(2).replaceAll("-", "/")}
          </text>
        ))}
        <path d={area} fill="var(--accent)" opacity={0.08} />
        <path d={path} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" />
        {hp && hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + ih} stroke="var(--muted)" strokeDasharray="3 3" />
            <circle cx={x(hover)} cy={y(hp.value)} r={4} fill="var(--accent)" stroke="var(--panel)" strokeWidth={2} />
          </g>
        )}
      </svg>
      {hp && hover !== null && (
        <div
          className="chart-tip"
          style={{ left: Math.min(x(hover) + 10, size.w - 140), top: Math.max(0, y(hp.value) - 48) }}
        >
          <div className="small muted">{hp.observed_on}</div>
          <b>{fmt(hp.value)}</b> <span className="small muted">{unit}</span>
        </div>
      )}
    </div>
  );
}
