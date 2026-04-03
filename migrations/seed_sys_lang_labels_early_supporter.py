#!/usr/bin/env python3
"""Seed i18n labels for Early Supporter badge + welcome email system."""
import psycopg2, psycopg2.extras, os

conn = psycopg2.connect(
    host=os.environ.get("PGHOST", "localhost"),
    port=int(os.environ.get("PGPORT", "5432")),
    dbname="postgres",
    user=os.environ.get("PGUSER", "postgres"),
    password=os.environ.get("PGPASSWORD", "postgres"),
)

# fmt: off
LABELS = [
    # Badge labels
    ("badge_early_supporter", "badge", {
        "en": "Early Supporter",
        "zh": "早期支持者",
        "zh-TW": "早期支持者",
        "ja": "アーリーサポーター",
        "ko": "얼리 서포터",
        "vi": "Người ủng hộ sớm",
        "th": "ผู้สนับสนุนรุ่นแรก",
        "ms": "Penyokong Awal",
    }),
    ("badge_early_supporter_desc", "badge", {
        "en": "One of our first 1,000 users",
        "zh": "我们的前1,000名用户之一",
        "zh-TW": "我們的前1,000名使用者之一",
        "ja": "最初の1,000人のユーザーの一人",
        "ko": "최초 1,000명 사용자 중 한 명",
        "vi": "Một trong 1.000 người dùng đầu tiên",
        "th": "หนึ่งในผู้ใช้ 1,000 คนแรกของเรา",
        "ms": "Salah seorang daripada 1,000 pengguna pertama kami",
    }),
    ("badge_early_supporter_hash", "badge", {
        "en": "Early Supporter #{n}",
        "zh": "早期支持者 #{n}",
        "zh-TW": "早期支持者 #{n}",
        "ja": "アーリーサポーター #{n}",
        "ko": "얼리 서포터 #{n}",
        "vi": "Người ủng hộ sớm #{n}",
        "th": "ผู้สนับสนุนรุ่นแรก #{n}",
        "ms": "Penyokong Awal #{n}",
    }),
    # Welcome email
    ("welcome_email_subject", "email", {
        "en": "Welcome to DataPAI, Early Supporter!",
        "zh": "欢迎加入DataPAI，早期支持者！",
        "zh-TW": "歡迎加入DataPAI，早期支持者！",
        "ja": "DataPAIへようこそ、アーリーサポーター！",
        "ko": "DataPAI에 오신 것을 환영합니다, 얼리 서포터!",
        "vi": "Chào mừng đến DataPAI, Người ủng hộ sớm!",
        "th": "ยินดีต้อนรับสู่ DataPAI ผู้สนับสนุนรุ่นแรก!",
        "ms": "Selamat datang ke DataPAI, Penyokong Awal!",
    }),
    ("welcome_email_greeting", "email", {
        "en": "Thank you for joining us early",
        "zh": "感谢您的早期加入",
        "zh-TW": "感謝您的早期加入",
        "ja": "早期参加いただきありがとうございます",
        "ko": "일찍 함께해 주셔서 감사합니다",
        "vi": "Cảm ơn bạn đã tham gia sớm",
        "th": "ขอบคุณที่เข้าร่วมตั้งแต่เนิ่นๆ",
        "ms": "Terima kasih kerana menyertai kami awal",
    }),
    ("welcome_email_badge_forever", "email", {
        "en": "You're one of our first users. This badge is yours forever.",
        "zh": "您是我们最早的用户之一。这个徽章将永远属于您。",
        "zh-TW": "您是我們最早的使用者之一。這個徽章將永遠屬於您。",
        "ja": "あなたは最初のユーザーの一人です。このバッジは永遠にあなたのものです。",
        "ko": "당신은 우리의 첫 번째 사용자 중 한 명입니다. 이 배지는 영원히 당신의 것입니다.",
        "vi": "Bạn là một trong những người dùng đầu tiên. Huy hiệu này mãi mãi thuộc về bạn.",
        "th": "คุณเป็นหนึ่งในผู้ใช้กลุ่มแรกของเรา ตราสัญลักษณ์นี้เป็นของคุณตลอดไป",
        "ms": "Anda adalah salah seorang pengguna pertama kami. Lencana ini milik anda selamanya.",
    }),
    ("welcome_step1", "email", {
        "en": "Search for a stock",
        "zh": "搜索股票",
        "zh-TW": "搜尋股票",
        "ja": "銘柄を検索",
        "ko": "주식 검색",
        "vi": "Tìm kiếm cổ phiếu",
        "th": "ค้นหาหุ้น",
        "ms": "Cari saham",
    }),
    ("welcome_step2", "email", {
        "en": "Add to your watchlist",
        "zh": "添加到关注列表",
        "zh-TW": "加入關注清單",
        "ja": "ウォッチリストに追加",
        "ko": "관심목록에 추가",
        "vi": "Thêm vào danh sách theo dõi",
        "th": "เพิ่มในรายการติดตาม",
        "ms": "Tambah ke senarai pantau",
    }),
    ("welcome_step3", "email", {
        "en": "Get AI-powered signals",
        "zh": "获取AI驱动的信号",
        "zh-TW": "取得AI驅動的訊號",
        "ja": "AIシグナルを取得",
        "ko": "AI 시그널 받기",
        "vi": "Nhận tín hiệu AI",
        "th": "รับสัญญาณ AI",
        "ms": "Dapatkan isyarat AI",
    }),
]
# fmt: on

cur = conn.cursor()
for label_key, category, translations in LABELS:
    for lang, text in translations.items():
        cur.execute(
            """
            INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (label_key, lang) DO UPDATE SET text = EXCLUDED.text, category = EXCLUDED.category
            """,
            (label_key, lang, text, category),
        )

conn.commit()
cur.close()
conn.close()
print(f"Seeded {len(LABELS)} label keys x 8 languages = {len(LABELS) * 8} rows")
