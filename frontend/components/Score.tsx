/** -2〜+2 のスコアを色付きチップで表示（好悪の評価用） */
export function ScoreChip({ label, score }: { label?: string; score: number | null }) {
  if (score === null || score === undefined) return <span className="chip s0">{label} -</span>;
  const s = Math.round(score);
  return (
    <span className={`chip s${s}`} title={String(score)}>
      {label} {score > 0 ? "+" : ""}
      {Number(score).toFixed(Number.isInteger(score) ? 0 : 1)}
    </span>
  );
}

/** 指標の方向（上昇/下落）を矢印で表示。好悪ではないので色は付けない */
export function Direction({ score }: { score: number }) {
  const arrows = score >= 2 ? "▲▲" : score >= 1 ? "▲" : score <= -2 ? "▼▼" : score <= -1 ? "▼" : "→";
  return <span title={String(score)}>{arrows} {score > 0 ? "+" : ""}{score}</span>;
}

export function Bar({ value }: { value: number }) {
  return (
    <div className="bar" title={`${value}`}>
      <span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const w = 160;
  const h = 32;
  const pts = values
    .map((v, i) => `${(i / (values.length - 1)) * w},${h - ((v - min) / (max - min || 1)) * h}`)
    .join(" ");
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ height: 32 }}>
      <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth="1.5" />
    </svg>
  );
}
