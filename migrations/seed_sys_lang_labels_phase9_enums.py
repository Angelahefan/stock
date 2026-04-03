#!/usr/bin/env python3
"""Phase 9 seed: Signal type, validation status, severity, change type enums."""
import psycopg2, psycopg2.extras, os

conn = psycopg2.connect(host=os.environ.get("PGHOST","localhost"), port=int(os.environ.get("PGPORT","5432")),
    dbname="postgres", user=os.environ.get("PGUSER","postgres"), password=os.environ.get("PGPASSWORD","postgres"))

# fmt: off
LABELS = [
    # Signal types
    ("signal_guidance_withdrawal", "enum", {"en":"Forward Guidance Withdrawal","zh":"前瞻性指引撤回","zh-TW":"前瞻性指引撤回","ja":"フォワードガイダンス撤回","ko":"향후 가이던스 철회","vi":"Rút hướng dẫn triển vọng","th":"ถอนแนวทางล่วงหน้า","ms":"Penarikan panduan hadapan"}),
    ("signal_risk_expansion", "enum", {"en":"Risk Disclosure Expansion","zh":"风险披露扩大","zh-TW":"風險披露擴大","ja":"リスク開示の拡大","ko":"리스크 공시 확대","vi":"Mở rộng công bố rủi ro","th":"การขยายการเปิดเผยความเสี่ยง","ms":"Pengembangan pendedahan risiko"}),
    ("signal_tone_softening", "enum", {"en":"Tone Softening","zh":"语气软化","zh-TW":"語氣軟化","ja":"トーンの軟化","ko":"어조 완화","vi":"Giảm nhẹ giọng điệu","th":"น้ำเสียงอ่อนลง","ms":"Pelembutan nada"}),
    ("signal_no_signal", "enum", {"en":"No signal","zh":"无信号","zh-TW":"無信號","ja":"シグナルなし","ko":"시그널 없음","vi":"Không có tín hiệu","th":"ไม่มีสัญญาณ","ms":"Tiada isyarat"}),

    # Validation status
    ("validation_confirmed", "enum", {"en":"Confirmed","zh":"已确认","zh-TW":"已確認","ja":"確認済み","ko":"확인됨","vi":"Đã xác nhận","th":"ยืนยันแล้ว","ms":"Disahkan"}),
    ("validation_partially", "enum", {"en":"Partially Confirmed","zh":"部分确认","zh-TW":"部分確認","ja":"一部確認","ko":"부분 확인","vi":"Xác nhận một phần","th":"ยืนยันบางส่วน","ms":"Disahkan sebahagian"}),
    ("validation_not_yet", "enum", {"en":"Not Confirmed Yet","zh":"尚未确认","zh-TW":"尚未確認","ja":"未確認","ko":"미확인","vi":"Chưa xác nhận","th":"ยังไม่ได้ยืนยัน","ms":"Belum disahkan"}),
    ("validation_unavailable", "enum", {"en":"Source Unavailable","zh":"来源不可用","zh-TW":"來源不可用","ja":"ソース不明","ko":"소스 불가","vi":"Nguồn không khả dụng","th":"แหล่งข้อมูลไม่พร้อม","ms":"Sumber tidak tersedia"}),

    # Severity
    ("severity_high", "enum", {"en":"HIGH","zh":"高","zh-TW":"高","ja":"高","ko":"높음","vi":"CAO","th":"สูง","ms":"TINGGI"}),
    ("severity_medium", "enum", {"en":"MEDIUM","zh":"中","zh-TW":"中","ja":"中","ko":"중간","vi":"TRUNG BÌNH","th":"ปานกลาง","ms":"SEDERHANA"}),
    ("severity_low", "enum", {"en":"LOW","zh":"低","zh-TW":"低","ja":"低","ko":"낮음","vi":"THẤP","th":"ต่ำ","ms":"RENDAH"}),

    # Change types
    ("change_content", "enum", {"en":"Content Change","zh":"内容变更","zh-TW":"內容變更","ja":"コンテンツ変更","ko":"콘텐츠 변경","vi":"Thay đổi nội dung","th":"เปลี่ยนแปลงเนื้อหา","ms":"Perubahan kandungan"}),
    ("change_archive", "enum", {"en":"Archive Change","zh":"归档变更","zh-TW":"歸檔變更","ja":"アーカイブ変更","ko":"아카이브 변경","vi":"Thay đổi lưu trữ","th":"เปลี่ยนแปลงเอกสาร","ms":"Perubahan arkib"}),
    ("change_layout", "enum", {"en":"Layout Change","zh":"布局变更","zh-TW":"佈局變更","ja":"レイアウト変更","ko":"레이아웃 변경","vi":"Thay đổi bố cục","th":"เปลี่ยนแปลงเลย์เอาท์","ms":"Perubahan susun atur"}),

    # Confidence labels
    ("conf_high", "enum", {"en":"High","zh":"高","zh-TW":"高","ja":"高","ko":"높음","vi":"Cao","th":"สูง","ms":"Tinggi"}),
    ("conf_growing", "enum", {"en":"Growing","zh":"增长中","zh-TW":"增長中","ja":"成長中","ko":"증가 중","vi":"Đang tăng","th":"กำลังเพิ่มขึ้น","ms":"Meningkat"}),
    ("conf_early", "enum", {"en":"Early signal","zh":"早期信号","zh-TW":"早期信號","ja":"初期シグナル","ko":"초기 시그널","vi":"Tín hiệu sớm","th":"สัญญาณเริ่มต้น","ms":"Isyarat awal"}),

    # All clear / no signal states
    ("ticker_all_clear", "ticker", {"en":"All clear","zh":"一切正常","zh-TW":"一切正常","ja":"問題なし","ko":"이상 없음","vi":"Bình thường","th":"ปกติ","ms":"Semua baik"}),
    ("ticker_not_detected", "ticker", {"en":"Not yet detected","zh":"尚未检测到","zh-TW":"尚未檢測到","ja":"未検出","ko":"미감지","vi":"Chưa phát hiện","th":"ยังไม่ตรวจพบ","ms":"Belum dikesan"}),
    ("ticker_monitored_no_signal", "ticker", {"en":"Monitored · no signal","zh":"监控中 · 无信号","zh-TW":"監控中 · 無信號","ja":"監視中 · シグナルなし","ko":"모니터링 중 · 시그널 없음","vi":"Đang theo dõi · không có tín hiệu","th":"กำลังติดตาม · ไม่มีสัญญาณ","ms":"Dipantau · tiada isyarat"}),
    ("ticker_detected_powered", "ticker", {"en":"Detected & powered by DataP.ai Financial Agents","zh":"由DataP.ai金融代理检测","zh-TW":"由DataP.ai金融代理檢測","ja":"DataP.ai金融エージェントが検出","ko":"DataP.ai 금융 에이전트가 감지","vi":"Phát hiện bởi DataP.ai Financial Agents","th":"ตรวจพบโดย DataP.ai Financial Agents","ms":"Dikesan oleh DataP.ai Financial Agents"}),
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
