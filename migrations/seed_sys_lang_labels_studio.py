#!/usr/bin/env python3
"""Seed i18n labels for Personalized Agent Studio feature."""
import psycopg2, psycopg2.extras, os

conn = psycopg2.connect(host=os.environ.get("PGHOST","localhost"), port=int(os.environ.get("PGPORT","5432")),
    dbname="postgres", user=os.environ.get("PGUSER","postgres"), password=os.environ.get("PGPASSWORD","postgres"))

# fmt: off
LABELS = [
    # Nav
    ("nav_studio", "nav", {
        "en": "Studio", "zh": "策略工坊", "zh-TW": "策略工坊", "ja": "スタジオ", "ko": "스튜디오", "vi": "Studio", "th": "สตูดิโอ", "ms": "Studio",
    }),
    # Studio list page
    ("studio_title", "studio", {
        "en": "Agent Studio", "zh": "AI策略工坊", "zh-TW": "AI策略工坊", "ja": "エージェントスタジオ", "ko": "에이전트 스튜디오", "vi": "Agent Studio", "th": "เอเจนต์สตูดิโอ", "ms": "Agent Studio",
    }),
    ("studio_subtitle", "studio", {
        "en": "Build, test, and optimise your trading strategies with AI-powered backtesting",
        "zh": "使用AI回测构建、测试和优化您的交易策略",
        "zh-TW": "使用AI回測構建、測試和優化您的交易策略",
        "ja": "AIバックテストで取引戦略を構築・テスト・最適化",
        "ko": "AI 백테스트로 매매 전략을 구축, 테스트, 최적화",
        "vi": "Xay dung, kiem tra va toi uu hoa chien luoc giao dich voi AI",
        "th": "สร้าง ทดสอบ และปรับปรุงกลยุทธ์การซื้อขายด้วย AI",
        "ms": "Bina, uji dan optimumkan strategi dagangan dengan AI",
    }),
    ("studio_create_new", "studio", {
        "en": "New Strategy", "zh": "新建策略", "zh-TW": "新建策略", "ja": "新規戦略", "ko": "새 전략", "vi": "Tao moi", "th": "สร้างใหม่", "ms": "Strategi Baru",
    }),
    ("studio_empty_title", "studio", {
        "en": "No strategies yet", "zh": "暂无策略", "zh-TW": "暫無策略", "ja": "戦略がまだありません", "ko": "전략이 없습니다", "vi": "Chua co chien luoc", "th": "ยังไม่มีกลยุทธ์", "ms": "Belum ada strategi",
    }),
    ("studio_empty_desc", "studio", {
        "en": "Create your first trading strategy and run a backtest to see how it would have performed.",
        "zh": "创建您的第一个交易策略并运行回测，查看其历史表现。",
        "zh-TW": "創建您的第一個交易策略並運行回測，查看其歷史表現。",
        "ja": "最初の取引戦略を作成し、バックテストを実行して過去のパフォーマンスを確認しましょう。",
        "ko": "첫 번째 매매 전략을 만들고 백테스트를 실행하여 성과를 확인하세요.",
        "vi": "Tao chien luoc giao dich dau tien va chay backtest de xem hieu suat.",
        "th": "สร้างกลยุทธ์แรกและทดสอบย้อนหลังเพื่อดูผลลัพธ์",
        "ms": "Buat strategi dagangan pertama anda dan jalankan ujian untuk melihat prestasi.",
    }),
    ("studio_create_first", "studio", {
        "en": "Create Your First Strategy", "zh": "创建第一个策略", "zh-TW": "創建第一個策略", "ja": "最初の戦略を作成", "ko": "첫 전략 만들기", "vi": "Tao chien luoc dau tien", "th": "สร้างกลยุทธ์แรก", "ms": "Buat Strategi Pertama",
    }),
    # Summary cards
    ("studio_return", "studio", {
        "en": "Return", "zh": "回报", "zh-TW": "回報", "ja": "リターン", "ko": "수익률", "vi": "Loi nhuan", "th": "ผลตอบแทน", "ms": "Pulangan",
    }),
    ("studio_sharpe", "studio", {
        "en": "Sharpe", "zh": "夏普", "zh-TW": "夏普", "ja": "シャープ", "ko": "샤프", "vi": "Sharpe", "th": "ชาร์ป", "ms": "Sharpe",
    }),
    ("studio_alpha", "studio", {
        "en": "Alpha", "zh": "超额收益", "zh-TW": "超額收益", "ja": "アルファ", "ko": "알파", "vi": "Alpha", "th": "อัลฟ่า", "ms": "Alpha",
    }),
    # Status messages
    ("studio_pending_msg", "studio", {
        "en": "Backtest queued — results available after nightly run",
        "zh": "回测已排队 — 结果将在每日运行后可用",
        "zh-TW": "回測已排隊 — 結果將在每日運行後可用",
        "ja": "バックテスト待機中 — 夜間実行後に結果が利用可能",
        "ko": "백테스트 대기중 — 야간 실행 후 결과 확인 가능",
        "vi": "Backtest dang cho — ket qua co sau khi chay dem",
        "th": "อยู่ในคิว — ผลลัพธ์จะพร้อมหลังรันกลางคืน",
        "ms": "Ujian dalam barisan — keputusan selepas larian malam",
    }),
    ("studio_running_msg", "studio", {
        "en": "Backtest in progress...", "zh": "回测进行中...", "zh-TW": "回測進行中...", "ja": "バックテスト実行中...", "ko": "백테스트 진행중...", "vi": "Dang chay backtest...", "th": "กำลังทดสอบ...", "ms": "Ujian sedang berjalan...",
    }),
    ("studio_failed_msg", "studio", {
        "en": "Backtest failed — edit strategy and retry",
        "zh": "回测失败 — 编辑策略后重试",
        "zh-TW": "回測失敗 — 編輯策略後重試",
        "ja": "バックテスト失敗 — 戦略を編集して再試行",
        "ko": "백테스트 실패 — 전략 수정 후 재시도",
        "vi": "Backtest that bai — sua va thu lai",
        "th": "ทดสอบล้มเหลว — แก้ไขและลองอีกครั้ง",
        "ms": "Ujian gagal — edit dan cuba semula",
    }),
    # Create page
    ("studio_back", "studio", {
        "en": "Back to Studio", "zh": "返回工坊", "zh-TW": "返回工坊", "ja": "スタジオに戻る", "ko": "스튜디오로 돌아가기", "vi": "Quay lai Studio", "th": "กลับสตูดิโอ", "ms": "Kembali ke Studio",
    }),
    ("studio_create_title", "studio", {
        "en": "Create Strategy", "zh": "创建策略", "zh-TW": "創建策略", "ja": "戦略を作成", "ko": "전략 만들기", "vi": "Tao chien luoc", "th": "สร้างกลยุทธ์", "ms": "Buat Strategi",
    }),
    ("studio_templates", "studio", {
        "en": "Quick Start Templates", "zh": "快速启动模板", "zh-TW": "快速啟動模板", "ja": "クイックスタートテンプレート", "ko": "빠른 시작 템플릿", "vi": "Mau khoi dong nhanh", "th": "เทมเพลตเริ่มต้นด่วน", "ms": "Templat Mula Pantas",
    }),
    ("studio_basic_info", "studio", {
        "en": "Basic Info", "zh": "基本信息", "zh-TW": "基本資訊", "ja": "基本情報", "ko": "기본 정보", "vi": "Thong tin co ban", "th": "ข้อมูลพื้นฐาน", "ms": "Maklumat Asas",
    }),
    ("studio_name", "studio", {
        "en": "Strategy Name", "zh": "策略名称", "zh-TW": "策略名稱", "ja": "戦略名", "ko": "전략 이름", "vi": "Ten chien luoc", "th": "ชื่อกลยุทธ์", "ms": "Nama Strategi",
    }),
    ("studio_type", "studio", {
        "en": "Strategy Type", "zh": "策略类型", "zh-TW": "策略類型", "ja": "戦略タイプ", "ko": "전략 유형", "vi": "Loai chien luoc", "th": "ประเภทกลยุทธ์", "ms": "Jenis Strategi",
    }),
    ("studio_description", "studio", {
        "en": "Description", "zh": "描述", "zh-TW": "描述", "ja": "説明", "ko": "설명", "vi": "Mo ta", "th": "คำอธิบาย", "ms": "Penerangan",
    }),
    ("studio_universe", "studio", {
        "en": "Universe", "zh": "股票池", "zh-TW": "股票池", "ja": "ユニバース", "ko": "유니버스", "vi": "Danh muc", "th": "จักรวาลหุ้น", "ms": "Alam Semesta",
    }),
    ("studio_exchange", "studio", {
        "en": "Exchange", "zh": "交易所", "zh-TW": "交易所", "ja": "取引所", "ko": "거래소", "vi": "San giao dich", "th": "ตลาดหลักทรัพย์", "ms": "Bursa",
    }),
    ("studio_all_featured", "studio", {
        "en": "All Featured Stocks", "zh": "所有精选股票", "zh-TW": "所有精選股票", "ja": "注目銘柄すべて", "ko": "모든 추천 종목", "vi": "Tat ca co phieu noi bat", "th": "หุ้นแนะนำทั้งหมด", "ms": "Semua Saham Pilihan",
    }),
    ("studio_select_tickers", "studio", {
        "en": "Select Tickers", "zh": "选择股票", "zh-TW": "選擇股票", "ja": "銘柄を選択", "ko": "종목 선택", "vi": "Chon co phieu", "th": "เลือกหุ้น", "ms": "Pilih Saham",
    }),
    ("studio_add", "studio", {
        "en": "Add", "zh": "添加", "zh-TW": "添加", "ja": "追加", "ko": "추가", "vi": "Them", "th": "เพิ่ม", "ms": "Tambah",
    }),
    ("studio_click_to_add", "studio", {
        "en": "Click to add/remove:", "zh": "点击添加/移除：", "zh-TW": "點擊添加/移除：", "ja": "クリックして追加/削除：", "ko": "클릭하여 추가/제거:", "vi": "Nhan de them/xoa:", "th": "คลิกเพื่อเพิ่ม/ลบ:", "ms": "Klik untuk tambah/buang:",
    }),
    ("studio_entry_rules", "studio", {
        "en": "Entry Rules", "zh": "入场规则", "zh-TW": "入場規則", "ja": "エントリールール", "ko": "진입 규칙", "vi": "Quy tac mua vao", "th": "กฎเข้าซื้อ", "ms": "Peraturan Masuk",
    }),
    ("studio_exit_rules", "studio", {
        "en": "Exit Rules", "zh": "出场规则", "zh-TW": "出場規則", "ja": "エグジットルール", "ko": "청산 규칙", "vi": "Quy tac ban ra", "th": "กฎขายออก", "ms": "Peraturan Keluar",
    }),
    ("studio_add_rule", "studio", {
        "en": "Add Rule", "zh": "添加规则", "zh-TW": "添加規則", "ja": "ルールを追加", "ko": "규칙 추가", "vi": "Them quy tac", "th": "เพิ่มกฎ", "ms": "Tambah Peraturan",
    }),
    ("studio_filters", "studio", {
        "en": "Filters & Sizing", "zh": "筛选与仓位", "zh-TW": "篩選與倉位", "ja": "フィルター＆サイジング", "ko": "필터 및 사이징", "vi": "Bo loc va kich thuoc", "th": "ตัวกรองและขนาด", "ms": "Penapis & Saiz",
    }),
    ("studio_min_volume", "studio", {
        "en": "Min Volume", "zh": "最低成交量", "zh-TW": "最低成交量", "ja": "最小出来高", "ko": "최소 거래량", "vi": "Khoi luong toi thieu", "th": "ปริมาณขั้นต่ำ", "ms": "Volum Minimum",
    }),
    ("studio_max_positions", "studio", {
        "en": "Max Positions", "zh": "最大持仓数", "zh-TW": "最大持倉數", "ja": "最大ポジション数", "ko": "최대 포지션 수", "vi": "So vi the toi da", "th": "ตำแหน่งสูงสุด", "ms": "Posisi Maksimum",
    }),
    ("studio_max_per_pos", "studio", {
        "en": "Max % per Position", "zh": "单仓最大占比%", "zh-TW": "單倉最大占比%", "ja": "1ポジション最大%", "ko": "포지션당 최대%", "vi": "% toi da/vi the", "th": "% สูงสุดต่อตำแหน่ง", "ms": "% Maks per Posisi",
    }),
    ("studio_backtest_params", "studio", {
        "en": "Backtest Parameters", "zh": "回测参数", "zh-TW": "回測參數", "ja": "バックテストパラメータ", "ko": "백테스트 매개변수", "vi": "Tham so backtest", "th": "พารามิเตอร์ทดสอบ", "ms": "Parameter Ujian",
    }),
    ("studio_start_date", "studio", {
        "en": "Start Date", "zh": "开始日期", "zh-TW": "開始日期", "ja": "開始日", "ko": "시작일", "vi": "Ngay bat dau", "th": "วันเริ่มต้น", "ms": "Tarikh Mula",
    }),
    ("studio_end_date", "studio", {
        "en": "End Date", "zh": "结束日期", "zh-TW": "結束日期", "ja": "終了日", "ko": "종료일", "vi": "Ngay ket thuc", "th": "วันสิ้นสุด", "ms": "Tarikh Tamat",
    }),
    ("studio_capital", "studio", {
        "en": "Initial Capital", "zh": "初始资金", "zh-TW": "初始資金", "ja": "初期資金", "ko": "초기 자본", "vi": "Von ban dau", "th": "ทุนเริ่มต้น", "ms": "Modal Awal",
    }),
    ("studio_commission", "studio", {
        "en": "Commission %", "zh": "佣金%", "zh-TW": "佣金%", "ja": "手数料%", "ko": "수수료%", "vi": "Hoa hong %", "th": "ค่าคอมมิชชั่น%", "ms": "Komisyen %",
    }),
    ("studio_cancel", "studio", {
        "en": "Cancel", "zh": "取消", "zh-TW": "取消", "ja": "キャンセル", "ko": "취소", "vi": "Huy", "th": "ยกเลิก", "ms": "Batal",
    }),
    ("studio_save_run", "studio", {
        "en": "Save & Run Backtest", "zh": "保存并运行回测", "zh-TW": "保存並運行回測", "ja": "保存してバックテスト実行", "ko": "저장 및 백테스트 실행", "vi": "Luu va chay backtest", "th": "บันทึกและรัน", "ms": "Simpan & Jalankan",
    }),
    ("studio_saving", "studio", {
        "en": "Saving...", "zh": "保存中...", "zh-TW": "保存中...", "ja": "保存中...", "ko": "저장중...", "vi": "Dang luu...", "th": "กำลังบันทึก...", "ms": "Menyimpan...",
    }),
    # Results page
    ("studio_run_backtest", "studio", {
        "en": "Run Backtest", "zh": "运行回测", "zh-TW": "運行回測", "ja": "バックテスト実行", "ko": "백테스트 실행", "vi": "Chay backtest", "th": "รันทดสอบ", "ms": "Jalankan Ujian",
    }),
    ("studio_delete", "studio", {
        "en": "Delete", "zh": "删除", "zh-TW": "刪除", "ja": "削除", "ko": "삭제", "vi": "Xoa", "th": "ลบ", "ms": "Padam",
    }),
    ("studio_total_return", "studio", {
        "en": "Total Return", "zh": "总回报", "zh-TW": "總回報", "ja": "総リターン", "ko": "총 수익률", "vi": "Tong loi nhuan", "th": "ผลตอบแทนรวม", "ms": "Pulangan Keseluruhan",
    }),
    ("studio_sharpe_ratio", "studio", {
        "en": "Sharpe Ratio", "zh": "夏普比率", "zh-TW": "夏普比率", "ja": "シャープレシオ", "ko": "샤프 비율", "vi": "Ti le Sharpe", "th": "อัตราส่วนชาร์ป", "ms": "Nisbah Sharpe",
    }),
    ("studio_max_dd", "studio", {
        "en": "Max Drawdown", "zh": "最大回撤", "zh-TW": "最大回撤", "ja": "最大ドローダウン", "ko": "최대 낙폭", "vi": "Sut giam toi da", "th": "การขาดทุนสูงสุด", "ms": "Kemerosotan Maks",
    }),
    ("studio_win_rate", "studio", {
        "en": "Win Rate", "zh": "胜率", "zh-TW": "勝率", "ja": "勝率", "ko": "승률", "vi": "Ti le thang", "th": "อัตราชนะ", "ms": "Kadar Kemenangan",
    }),
    ("studio_vs_sp500", "studio", {
        "en": "vs S&P 500", "zh": "超额回报", "zh-TW": "超額回報", "ja": "S&P 500比較", "ko": "vs S&P 500", "vi": "vs S&P 500", "th": "เทียบ S&P 500", "ms": "vs S&P 500",
    }),
    ("studio_trades", "studio", {
        "en": "Total Trades", "zh": "总交易数", "zh-TW": "總交易數", "ja": "総取引数", "ko": "총 거래 수", "vi": "Tong giao dich", "th": "รวมจำนวนซื้อขาย", "ms": "Jumlah Dagangan",
    }),
    ("studio_initial", "studio", {
        "en": "Initial Capital", "zh": "初始资金", "zh-TW": "初始資金", "ja": "初期資金", "ko": "초기 자본", "vi": "Von ban dau", "th": "ทุนเริ่มต้น", "ms": "Modal Awal",
    }),
    ("studio_final", "studio", {
        "en": "Final Capital", "zh": "最终资金", "zh-TW": "最終資金", "ja": "最終資金", "ko": "최종 자본", "vi": "Von cuoi", "th": "ทุนสุดท้าย", "ms": "Modal Akhir",
    }),
    ("studio_benchmark", "studio", {
        "en": "Benchmark", "zh": "基准", "zh-TW": "基準", "ja": "ベンチマーク", "ko": "벤치마크", "vi": "Tieu chuan", "th": "เกณฑ์มาตรฐาน", "ms": "Penanda Aras",
    }),
    ("studio_avg_trade", "studio", {
        "en": "Avg Trade", "zh": "平均交易", "zh-TW": "平均交易", "ja": "平均取引", "ko": "평균 거래", "vi": "Trung binh", "th": "เฉลี่ยต่อครั้ง", "ms": "Purata Dagangan",
    }),
    ("studio_tab_overview", "studio", {
        "en": "Equity Curve", "zh": "权益曲线", "zh-TW": "權益曲線", "ja": "エクイティカーブ", "ko": "자산 곡선", "vi": "Bieu do von", "th": "เส้นกราฟทุน", "ms": "Keluk Ekuiti",
    }),
    ("studio_tab_trades", "studio", {
        "en": "Trade Log", "zh": "交易记录", "zh-TW": "交易記錄", "ja": "取引ログ", "ko": "거래 기록", "vi": "Nhat ky giao dich", "th": "บันทึกการซื้อขาย", "ms": "Log Dagangan",
    }),
    ("studio_tab_monthly", "studio", {
        "en": "Monthly Returns", "zh": "月度回报", "zh-TW": "月度回報", "ja": "月次リターン", "ko": "월간 수익률", "vi": "Loi nhuan hang thang", "th": "ผลตอบแทนรายเดือน", "ms": "Pulangan Bulanan",
    }),
    ("studio_equity_curve", "studio", {
        "en": "Equity Curve", "zh": "权益曲线", "zh-TW": "權益曲線", "ja": "エクイティカーブ", "ko": "자산 곡선", "vi": "Bieu do von", "th": "เส้นกราฟทุน", "ms": "Keluk Ekuiti",
    }),
    ("studio_monthly_title", "studio", {
        "en": "Monthly Returns", "zh": "月度回报", "zh-TW": "月度回報", "ja": "月次リターン", "ko": "월간 수익률", "vi": "Loi nhuan hang thang", "th": "ผลตอบแทนรายเดือน", "ms": "Pulangan Bulanan",
    }),
    # Trade table columns
    ("studio_ticker", "studio", {
        "en": "Ticker", "zh": "代码", "zh-TW": "代碼", "ja": "ティッカー", "ko": "종목", "vi": "Ma", "th": "รหัสหุ้น", "ms": "Kod Saham",
    }),
    ("studio_entry_date", "studio", {
        "en": "Entry", "zh": "买入日", "zh-TW": "買入日", "ja": "エントリー日", "ko": "진입일", "vi": "Ngay mua", "th": "วันซื้อ", "ms": "Tarikh Masuk",
    }),
    ("studio_entry_price", "studio", {
        "en": "Entry Price", "zh": "买入价", "zh-TW": "買入價", "ja": "エントリー価格", "ko": "진입가", "vi": "Gia mua", "th": "ราคาซื้อ", "ms": "Harga Masuk",
    }),
    ("studio_exit_date", "studio", {
        "en": "Exit", "zh": "卖出日", "zh-TW": "賣出日", "ja": "エグジット日", "ko": "청산일", "vi": "Ngay ban", "th": "วันขาย", "ms": "Tarikh Keluar",
    }),
    ("studio_exit_price", "studio", {
        "en": "Exit Price", "zh": "卖出价", "zh-TW": "賣出價", "ja": "エグジット価格", "ko": "청산가", "vi": "Gia ban", "th": "ราคาขาย", "ms": "Harga Keluar",
    }),
    ("studio_return_col", "studio", {
        "en": "Return", "zh": "回报", "zh-TW": "回報", "ja": "リターン", "ko": "수익률", "vi": "Loi nhuan", "th": "ผลตอบแทน", "ms": "Pulangan",
    }),
    ("studio_signal", "studio", {
        "en": "Signal", "zh": "信号", "zh-TW": "信號", "ja": "シグナル", "ko": "신호", "vi": "Tin hieu", "th": "สัญญาณ", "ms": "Isyarat",
    }),
    # Pending/running states on result page
    ("studio_pending_title", "studio", {
        "en": "Backtest Queued", "zh": "回测已排队", "zh-TW": "回測已排隊", "ja": "バックテスト待機中", "ko": "백테스트 대기중", "vi": "Backtest dang cho", "th": "อยู่ในคิว", "ms": "Ujian Dalam Barisan",
    }),
    ("studio_running_title", "studio", {
        "en": "Backtest Running", "zh": "回测运行中", "zh-TW": "回測運行中", "ja": "バックテスト実行中", "ko": "백테스트 실행중", "vi": "Dang chay backtest", "th": "กำลังทดสอบ", "ms": "Ujian Sedang Berjalan",
    }),
    ("studio_pending_desc", "studio", {
        "en": "Your backtest is queued. Results will be available after the nightly run at 02:00 UTC.",
        "zh": "回测已排队。结果将在每日UTC 02:00运行后可用。",
        "zh-TW": "回測已排隊。結果將在每日UTC 02:00運行後可用。",
        "ja": "バックテストは待機中です。UTC 02:00の夜間実行後に結果が利用可能になります。",
        "ko": "백테스트가 대기중입니다. UTC 02:00 야간 실행 후 결과를 확인할 수 있습니다.",
        "vi": "Backtest dang cho. Ket qua se co sau khi chay luc 02:00 UTC.",
        "th": "อยู่ในคิว ผลลัพธ์จะพร้อมหลังรันกลางคืนเวลา 02:00 UTC",
        "ms": "Ujian dalam barisan. Keputusan akan tersedia selepas larian malam pada 02:00 UTC.",
    }),
    ("studio_running_desc", "studio", {
        "en": "Your backtest is currently running. Please check back shortly.",
        "zh": "回测正在运行中，请稍后查看。",
        "zh-TW": "回測正在運行中，請稍後查看。",
        "ja": "バックテストは現在実行中です。しばらくしてから確認してください。",
        "ko": "백테스트가 진행중입니다. 잠시 후 다시 확인해주세요.",
        "vi": "Backtest dang chay. Vui long quay lai sau.",
        "th": "กำลังทดสอบ กรุณากลับมาตรวจสอบภายหลัง",
        "ms": "Ujian sedang berjalan. Sila semak semula sebentar lagi.",
    }),
    ("studio_failed_desc", "studio", {
        "en": "The backtest failed. Try editing your strategy and running again.",
        "zh": "回测失败。请编辑策略后重新运行。",
        "zh-TW": "回測失敗。請編輯策略後重新運行。",
        "ja": "バックテストが失敗しました。戦略を編集して再実行してください。",
        "ko": "백테스트가 실패했습니다. 전략을 수정하고 다시 실행해주세요.",
        "vi": "Backtest that bai. Sua chien luoc va chay lai.",
        "th": "ทดสอบล้มเหลว แก้ไขกลยุทธ์แล้วลองอีกครั้ง",
        "ms": "Ujian gagal. Cuba edit strategi dan jalankan semula.",
    }),
    ("studio_no_results_title", "studio", {
        "en": "No Results", "zh": "暂无结果", "zh-TW": "暫無結果", "ja": "結果なし", "ko": "결과 없음", "vi": "Chua co ket qua", "th": "ไม่มีผลลัพธ์", "ms": "Tiada Keputusan",
    }),
    ("studio_no_results_desc", "studio", {
        "en": "Click 'Run Backtest' to start.", "zh": "点击'运行回测'开始。", "zh-TW": "點擊'運行回測'開始。", "ja": "'バックテスト実行'をクリックして開始。", "ko": "'백테스트 실행'을 클릭하여 시작하세요.", "vi": "Nhan 'Chay backtest' de bat dau.", "th": "คลิก 'รันทดสอบ' เพื่อเริ่ม", "ms": "Klik 'Jalankan Ujian' untuk mula.",
    }),
]
# fmt: on

rows = []
for key, cat, trans in LABELS:
    for lang, text in trans.items():
        rows.append((key, lang, text, cat))

print(f"Seeding {len(rows)} label rows ({len(LABELS)} keys x 8 languages)...")
with conn.cursor() as cur:
    psycopg2.extras.execute_values(cur,
        """INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES %s
           ON CONFLICT (label_key, lang) DO UPDATE SET text = EXCLUDED.text, category = EXCLUDED.category, updated_at = NOW()""",
        rows, template="(%s, %s, %s, %s)")
    conn.commit()
    print(f"Upserted {cur.rowcount} rows.")
    cur.execute("SELECT COUNT(*) FROM datapai.sys_lang_labels")
    print(f"Total labels in DB: {cur.fetchone()[0]}")
conn.close()
