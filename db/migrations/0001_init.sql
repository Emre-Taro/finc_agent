-- finc_agent 初期スキーマ（PostgreSQL 13 以上）
-- 適用: psql "$DATABASE_URL" -f db/migrations/0001_init.sql

-- 取得/更新ジョブの実行ログ（1日3回の取得状況の確認用）
create table if not exists ingest_runs (
    id           uuid primary key default gen_random_uuid(),
    kind         text not null check (kind in ('news', 'indicators', 'company_scores')),
    started_at   timestamptz not null default now(),
    finished_at  timestamptz,
    status       text not null default 'running' check (status in ('running', 'success', 'partial', 'failed')),
    stats        jsonb not null default '{}'::jsonb,
    error        text
);

-- ニュース本体
create table if not exists news (
    id                  uuid primary key default gen_random_uuid(),
    published_at        timestamptz,
    fetched_at          timestamptz not null default now(),
    title               text not null,
    url                 text not null,
    -- 重複防止: 正規化URLのSHA-256（utm等のトラッキングパラメータ・#以降を除去済み）
    url_hash            text not null unique,
    -- 重複防止: 同一媒体で URL だけ違う同一記事を弾くための正規化タイトルのハッシュ
    title_hash          text not null,
    source              text not null,
    feed_name           text,
    raw_excerpt         text,
    content_summary     text,
    macro_score         numeric(3, 1) check (macro_score between -2 and 2),
    industry_score      numeric(3, 1) check (industry_score between -2 and 2),
    ticker_score        numeric(3, 1) check (ticker_score between -2 and 2),
    primary_sector      text,
    primary_ticker      text,
    ai_analysis_reason  text,
    analysis_status     text not null default 'pending' check (analysis_status in ('pending', 'done', 'failed')),
    analysis_error      text,
    analyzed_at         timestamptz,
    ingest_run_id       uuid references ingest_runs (id) on delete set null,
    unique (source, title_hash)
);
create index if not exists news_published_at_idx on news (published_at desc);
create index if not exists news_status_idx on news (analysis_status);

-- 各ニュースが業界・指標・個別銘柄に与える影響（全セクター/全指標を1行ずつ保存）
create table if not exists news_impacts (
    id           bigint generated always as identity primary key,
    news_id      uuid not null references news (id) on delete cascade,
    target_type  text not null check (target_type in ('sector', 'indicator', 'ticker')),
    target_code  text not null,
    target_name  text,
    score        numeric(3, 1) not null check (score between -2 and 2),
    reason       text,
    unique (news_id, target_type, target_code)
);
create index if not exists news_impacts_target_idx on news_impacts (target_type, target_code);

-- 金融指標の時系列
create table if not exists indicator_observations (
    indicator_code  text not null,
    observed_on     date not null,
    value           double precision not null,
    source          text not null,
    fetched_at      timestamptz not null default now(),
    primary key (indicator_code, observed_on)
);

-- ウォッチリスト銘柄
create table if not exists companies (
    ticker      text primary key,
    name        text not null,
    sector      text not null,
    created_at  timestamptz not null default now()
);

-- 銘柄スコア（マクロ / 業界 / 個別 の3軸、各100点満点）
create table if not exists company_scores (
    id               uuid primary key default gen_random_uuid(),
    ticker           text not null references companies (ticker) on delete cascade,
    scored_at        timestamptz not null default now(),
    macro_score      numeric(5, 1) not null check (macro_score between 0 and 100),
    industry_score   numeric(5, 1) not null check (industry_score between 0 and 100),
    ticker_score     numeric(5, 1) not null check (ticker_score between 0 and 100),
    total_score      numeric(5, 1) not null check (total_score between 0 and 100),
    macro_reason     text,
    industry_reason  text,
    ticker_reason    text,
    summary          text,
    evidence         jsonb not null default '{}'::jsonb
);
create index if not exists company_scores_ticker_idx on company_scores (ticker, scored_at desc);

-- 直近 p_days 日のニュースによるセクター/指標への影響の平均（ダッシュボードのヒートマップ用）
create or replace function impact_summary(p_days int default 7)
returns table (target_type text, target_code text, avg_score numeric, nonzero_count bigint, news_count bigint)
language sql stable as $$
    select i.target_type,
           i.target_code,
           round(avg(i.score), 2),
           count(*) filter (where i.score <> 0),
           count(*)
    from news_impacts i
    join news n on n.id = i.news_id
    where i.target_type in ('sector', 'indicator')
      and n.published_at >= now() - make_interval(days => p_days)
    group by i.target_type, i.target_code
$$;
