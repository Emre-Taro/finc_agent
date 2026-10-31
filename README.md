# finc_agent
AI Agent for individual investors

Bloomberg / Reuters / Financial Times / 日本経済新聞 のRSSから金融ニュースを集め、Claude で
「マクロ・業界・個別銘柄」への影響と、各セクター・債券利回り・インフレ等の指標への影響を評価します。
蓄積した評価と金融指標をもとに、ウォッチリストの銘柄を3軸（各100点満点）でスコアリングします。

```
frontend/  Next.js（ダッシュボード / 銘柄スコア画面）
backend/   FastAPI（RSS取得・AI評価・指標取得・スコアリング）
db/        PostgreSQL スキーマ
```

## セットアップ

### 1. データベース（PostgreSQL 13 以上）
ローカルの PostgreSQL でも、Neon などのマネージド PostgreSQL でも動きます（接続先は `DATABASE_URL` だけ）。

```bash
createdb finc_agent                                   # ローカルの場合
psql "$DATABASE_URL" -f db/migrations/0001_init.sql
```

### 2. バックエンド
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # ANTHROPIC_API_KEY, DATABASE_URL, FRED_API_KEY を記入
uvicorn app.main:app --reload --port 8000
```
API ドキュメント: http://localhost:8000/docs

FRED APIキーは https://fred.stlouisfed.org/docs/api/api_key.html で無料発行できます。

### 3. フロントエンド
```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```
http://localhost:3000 を開き、「ニュースを取得してAI評価」「金融指標を更新」を押します。

## 仕組み

### ニュース収集と重複防止
| 媒体 | フィード |
|---|---|
| Bloomberg | 公式RSS（Markets, Economics） |
| Financial Times | 公式RSS（Markets, Global Economy） |
| Reuters | 公式RSSが廃止されているため Google News RSS（`site:reuters.com`） |
| 日本経済新聞 | 公開RSSが無いため Google News RSS（`site:nikkei.com`） |

各社とも有料記事が多いため本文は取得せず、タイトルとRSSの概要だけをAIに渡します。

重複は次の3段で防ぎます（`backend/app/ingest.py`）。
1. 同一バッチ内で、正規化URL（utm等のトラッキングパラメータと `#` 以降を除去）のハッシュと、
   媒体＋正規化タイトル（記号・空白・全角半角の揺れを除去）のハッシュで除外
2. `news.url_hash` と `(source, title_hash)` の UNIQUE 制約 + `INSERT ... ON CONFLICT DO NOTHING`。
   保存済みの記事は1文でスキップされ、同時実行でも重複しない
3. 記事を先に保存してから評価。AI評価は未評価の行だけが対象なので、既存記事に課金は発生しない。
   評価に失敗した記事は `failed` として残り、「失敗・未評価を再評価」で再実行

ボタンの連打で同じジョブが二重に走らないよう、実行中は 409 を返します。

### AI評価（1記事ごと）
- `macro_score` / `industry_score` / `ticker_score`: -2〜+2（好材料が +）
- 全11セクター（GICS）への影響: -2〜+2（好材料が +）
- 全13指標（米10年債・米2年債・日本10年債・米/日インフレ・FRB/日銀金利・ドル円・原油・金・S&P500・日経平均・VIX）
  への影響: **方向**を -2〜+2（上昇が +。好悪ではない）
- 言及された個別銘柄への影響

構造化出力（JSONスキーマ）で全セクター・全指標を必須キーにしているため、抜け漏れは起きません。
結果は `news` と `news_impacts` に保存されます。

### 銘柄スコア（100点満点 × 3軸）
| 軸 | 材料 |
|---|---|
| マクロ | 直近7日のマクロニュース + 最新の金融指標。企業ごとの感応度（円安が追い風か等）をAIが判断 |
| 業界 | 直近14日の、その銘柄のセクターへの影響評価 |
| 個別 | 直近30日の、その銘柄（ティッカー一致）への影響評価 |

ニュース評価の平均から「定量ベースライン」（50 + 25 × 平均）を計算し、それを出発点にAIが調整します。
総合 = マクロ×0.3 + 業界×0.3 + 個別×0.4（`backend/app/scoring.py` の `WEIGHTS`）。

### 金融指標
FRED（米国債利回り、FF金利、期待インフレ率、米CPI前年比、日本10年債〔月次〕、失業率）と
Yahoo Finance（ドル円、S&P500、日経平均、VIX、WTI、金）から取得し、`indicator_observations` に upsert します。

## コストの目安
既定モデルは `claude-haiku-5-5`（effort: ニュース評価は medium、銘柄採点は high）。初回はフィード全体で
150件前後の記事を評価し、目安は数十円程度です。精度を上げたい場合は `.env` の `CLAUDE_MODEL` を
`claude-sonnet-5-5` や `claude-opus-5-5` に変更してください。

## 1日3回の自動取得にしたい場合
`POST /api/ingest/news` を叩くだけなので、cron や Windows のタスクスケジューラ、GitHub Actions などから
1日3回呼び出せば自動化できます。
