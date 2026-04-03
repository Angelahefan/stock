#!/usr/bin/env python3
"""Phase 10 seed: Watchlist AI Overview section labels."""
import psycopg2, psycopg2.extras, os

conn = psycopg2.connect(host=os.environ.get("PGHOST","localhost"), port=int(os.environ.get("PGPORT","5432")),
    dbname="postgres", user=os.environ.get("PGUSER","postgres"), password=os.environ.get("PGPASSWORD","postgres"))

# fmt: off
LABELS = [
    ("wl_ai_overview", "watchlist", {"en":"AI Watchlist Overview","zh":"AI关注列表概览","zh-TW":"AI關注清單概覽","ja":"AIウォッチリスト概要","ko":"AI 관심목록 개요","vi":"Tổng quan AI danh sách theo dõi","th":"ภาพรวม AI รายการติดตาม","ms":"Gambaran keseluruhan AI senarai pantau"}),
    ("wl_debate_across", "watchlist", {"en":"AG2 multi-agent debate across","zh":"AG2多代理辩论覆盖","zh-TW":"AG2多代理辯論覆蓋","ja":"AG2マルチエージェント分析","ko":"AG2 멀티에이전트 토론","vi":"AG2 phân tích đa tác nhân","th":"การวิเคราะห์หลายเอเจนต์ AG2","ms":"Perbahasan berbilang ejen AG2"}),
    ("wl_stocks", "watchlist", {"en":"stocks","zh":"只股票","zh-TW":"隻股票","ja":"銘柄","ko":"종목","vi":"cổ phiếu","th":"หุ้น","ms":"saham"}),
    ("wl_updated", "watchlist", {"en":"updated","zh":"更新于","zh-TW":"更新於","ja":"更新日","ko":"업데이트","vi":"cập nhật","th":"อัปเดต","ms":"dikemas kini"}),
    ("wl_avg_confidence", "watchlist", {"en":"Avg Confidence","zh":"平均置信度","zh-TW":"平均置信度","ja":"平均信頼度","ko":"평균 신뢰도","vi":"Độ tin cậy TB","th":"ความมั่นใจเฉลี่ย","ms":"Keyakinan purata"}),
    ("wl_news_alerts", "watchlist", {"en":"News Alerts","zh":"新闻预警","zh-TW":"新聞預警","ja":"ニュースアラート","ko":"뉴스 알림","vi":"Cảnh báo tin tức","th":"การแจ้งเตือนข่าว","ms":"Amaran berita"}),
    ("wl_top_sell", "watchlist", {"en":"Top Sell Signals","zh":"主要卖出信号","zh-TW":"主要賣出信號","ja":"主要売りシグナル","ko":"주요 매도 시그널","vi":"Tín hiệu bán hàng đầu","th":"สัญญาณขายสำคัญ","ms":"Isyarat jual teratas"}),
    ("wl_top_buy", "watchlist", {"en":"Top Buy Signals","zh":"主要买入信号","zh-TW":"主要買入信號","ja":"主要買いシグナル","ko":"주요 매수 시그널","vi":"Tín hiệu mua hàng đầu","th":"สัญญาณซื้อสำคัญ","ms":"Isyarat beli teratas"}),
    ("wl_bullish", "watchlist", {"en":"BULLISH","zh":"看涨","zh-TW":"看漲","ja":"強気","ko":"강세","vi":"TĂNG","th":"ขาขึ้น","ms":"MENAIK"}),
    ("wl_bearish", "watchlist", {"en":"BEARISH","zh":"看跌","zh-TW":"看跌","ja":"弱気","ko":"약세","vi":"GIẢM","th":"ขาลง","ms":"MENURUN"}),
    ("wl_mixed", "watchlist", {"en":"MIXED","zh":"混合","zh-TW":"混合","ja":"混合","ko":"혼합","vi":"HỖN HỢP","th":"ผสม","ms":"BERCAMPUR"}),
    ("wl_critical_news", "watchlist", {"en":"critical news","zh":"重要新闻","zh-TW":"重要新聞","ja":"重要ニュース","ko":"중요 뉴스","vi":"tin tức quan trọng","th":"ข่าวสำคัญ","ms":"berita kritikal"}),
]
# fmt: on

rows = []
for key, cat, trans in LABELS:
    for lang, text in trans.items():
        rows.append((key, lang, text, cat))

print(f"Seeding {len(rows)} rows ({len(LABELS)} keys × 8 langs)...")
with conn.cursor() as cur:
    psycopg2.extras.execute_values(cur,
        """INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES %s
           ON CONFLICT (label_key, lang) DO UPDATE SET text = EXCLUDED.text, category = EXCLUDED.category, updated_at = NOW()""",
        rows, template="(%s, %s, %s, %s)")
    conn.commit()
    print(f"Upserted {cur.rowcount} rows.")
    cur.execute("SELECT COUNT(*) FROM datapai.sys_lang_labels")
    print(f"Total: {cur.fetchone()[0]}")
conn.close()
print("Done.")
