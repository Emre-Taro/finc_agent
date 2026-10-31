"use client";

import { useEffect, useRef, useState } from "react";
import { api, type TickerCandidate } from "@/lib/api";

/** 社名・証券コード・ティッカーを入力すると候補を出し、選ぶと onSelect を呼ぶ */
export function TickerSearch({ onSelect }: { onSelect: (c: TickerCandidate) => void }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<TickerCandidate[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const query = q.trim();
    if (!query) {
      setItems([]);
      return;
    }
    let cancelled = false;
    // 入力のたびに問い合わせないよう少し待つ
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await api<TickerCandidate[]>(`/api/tickers/search?q=${encodeURIComponent(query)}`);
        if (!cancelled) {
          setItems(res);
          setActive(0);
          setOpen(true);
        }
      } catch {
        if (!cancelled) setItems([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [q]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  function choose(c: TickerCandidate) {
    onSelect(c);
    setQ("");
    setItems([]);
    setOpen(false);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || items.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(items[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="combo" ref={boxRef}>
      <input
        className="combo-input"
        placeholder="銘柄を検索（例: トヨタ, 7203, nvidia, AAPL）"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => items.length && setOpen(true)}
        onKeyDown={onKeyDown}
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
      />
      {loading && <span className="combo-status small muted">検索中…</span>}
      {open && q.trim() && !loading && (
        <ul className="combo-list" role="listbox">
          {items.length === 0 && <li className="combo-empty small muted">候補が見つかりません</li>}
          {items.map((c, i) => (
            <li
              key={c.symbol}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(c);
              }}
            >
              <b>{c.symbol}</b> {c.name}
              <div className="small muted">
                {[c.exchange, c.sector_detail].filter(Boolean).join(" · ")}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
