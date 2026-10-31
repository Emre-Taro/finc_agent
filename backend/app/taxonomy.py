"""AI評価で使うセクター・指標の定義。

ニュース分析では、ここに並ぶ全セクター・全指標について必ずスコアを出させる
（JSONスキーマで必須キーにしているので抜け漏れが起きない）。
"""

# GICS 11セクター
SECTORS: dict[str, str] = {
    "energy": "エネルギー",
    "materials": "素材",
    "industrials": "資本財・サービス",
    "consumer_discretionary": "一般消費財",
    "consumer_staples": "生活必需品",
    "health_care": "ヘルスケア",
    "financials": "金融",
    "information_technology": "情報技術",
    "communication_services": "コミュニケーション",
    "utilities": "公益",
    "real_estate": "不動産",
}

# ニュースが影響を与えうる指標。スコアは「その指標が上がるか下がるか」の方向（+2=大きく上昇）。
NEWS_INDICATORS: dict[str, str] = {
    "US10Y": "米10年債利回り",
    "US2Y": "米2年債利回り",
    "JGB10Y": "日本10年債利回り",
    "US_INFLATION": "米インフレ率",
    "JP_INFLATION": "日本インフレ率",
    "FED_RATE": "FRB政策金利（見通し）",
    "BOJ_RATE": "日銀政策金利（見通し）",
    "USDJPY": "ドル円",
    "WTI": "原油(WTI)",
    "GOLD": "金",
    "SPX": "S&P500",
    "N225": "日経平均",
    "VIX": "VIX（恐怖指数）",
}
