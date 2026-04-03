#!/usr/bin/env python3
"""
send_welcome_email.py — Send welcome email to new DataPAI Early Supporters via AWS SES.

Usage:
    # Called from registration API or directly:
    python scripts/send_welcome_email.py --email user@example.com --badge-number 7 --lang vi

Env:
    DATAPAI_SES_FROM_EMAIL  — verified SES sender (e.g. noreply@datap.ai)
    AWS_REGION              — SES region (default: ap-southeast-2)
    AWS_ACCESS_KEY_ID       — (optional if using IAM role)
    AWS_SECRET_ACCESS_KEY   — (optional if using IAM role)
"""

import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# i18n translations for the email (embedded fallback — DB labels preferred if available)
EMAIL_TRANSLATIONS = {
    "en": {
        "subject": "Welcome to DataPAI, Early Supporter!",
        "greeting": "Thank you for joining us early",
        "badge_forever": "You're one of our first users. This badge is yours forever.",
        "step1": "Search for a stock",
        "step2": "Add to your watchlist",
        "step3": "Get AI-powered signals",
        "cta": "Open DataPAI",
        "quick_start": "Quick Start Guide",
    },
    "zh": {
        "subject": "欢迎加入DataPAI，早期支持者！",
        "greeting": "感谢您的早期加入",
        "badge_forever": "您是我们最早的用户之一。这个徽章将永远属于您。",
        "step1": "搜索股票",
        "step2": "添加到关注列表",
        "step3": "获取AI驱动的信号",
        "cta": "打开 DataPAI",
        "quick_start": "快速入门",
    },
    "zh-TW": {
        "subject": "歡迎加入DataPAI，早期支持者！",
        "greeting": "感謝您的早期加入",
        "badge_forever": "您是我們最早的使用者之一。這個徽章將永遠屬於您。",
        "step1": "搜尋股票",
        "step2": "加入關注清單",
        "step3": "取得AI驅動的訊號",
        "cta": "開啟 DataPAI",
        "quick_start": "快速入門",
    },
    "ja": {
        "subject": "DataPAIへようこそ、アーリーサポーター！",
        "greeting": "早期参加いただきありがとうございます",
        "badge_forever": "あなたは最初のユーザーの一人です。このバッジは永遠にあなたのものです。",
        "step1": "銘柄を検索",
        "step2": "ウォッチリストに追加",
        "step3": "AIシグナルを取得",
        "cta": "DataPAIを開く",
        "quick_start": "クイックスタート",
    },
    "ko": {
        "subject": "DataPAI에 오신 것을 환영합니다, 얼리 서포터!",
        "greeting": "일찍 함께해 주셔서 감사합니다",
        "badge_forever": "당신은 우리의 첫 번째 사용자 중 한 명입니다. 이 배지는 영원히 당신의 것입니다.",
        "step1": "주식 검색",
        "step2": "관심목록에 추가",
        "step3": "AI 시그널 받기",
        "cta": "DataPAI 열기",
        "quick_start": "빠른 시작",
    },
    "vi": {
        "subject": "Chào mừng đến DataPAI, Người ủng hộ sớm!",
        "greeting": "Cảm ơn bạn đã tham gia sớm",
        "badge_forever": "Bạn là một trong những người dùng đầu tiên. Huy hiệu này mãi mãi thuộc về bạn.",
        "step1": "Tìm kiếm cổ phiếu",
        "step2": "Thêm vào danh sách theo dõi",
        "step3": "Nhận tín hiệu AI",
        "cta": "Mở DataPAI",
        "quick_start": "Hướng dẫn bắt đầu",
    },
    "th": {
        "subject": "ยินดีต้อนรับสู่ DataPAI ผู้สนับสนุนรุ่นแรก!",
        "greeting": "ขอบคุณที่เข้าร่วมตั้งแต่เนิ่นๆ",
        "badge_forever": "คุณเป็นหนึ่งในผู้ใช้กลุ่มแรกของเรา ตราสัญลักษณ์นี้เป็นของคุณตลอดไป",
        "step1": "ค้นหาหุ้น",
        "step2": "เพิ่มในรายการติดตาม",
        "step3": "รับสัญญาณ AI",
        "cta": "เปิด DataPAI",
        "quick_start": "เริ่มต้นอย่างรวดเร็ว",
    },
    "ms": {
        "subject": "Selamat datang ke DataPAI, Penyokong Awal!",
        "greeting": "Terima kasih kerana menyertai kami awal",
        "badge_forever": "Anda adalah salah seorang pengguna pertama kami. Lencana ini milik anda selamanya.",
        "step1": "Cari saham",
        "step2": "Tambah ke senarai pantau",
        "step3": "Dapatkan isyarat AI",
        "cta": "Buka DataPAI",
        "quick_start": "Panduan Mula Pantas",
    },
}


def build_html_email(badge_number: int, lang: str = "en") -> str:
    """Build beautiful HTML welcome email with Early Supporter badge."""
    tr = EMAIL_TRANSLATIONS.get(lang, EMAIL_TRANSLATIONS["en"])
    app_url = "https://platform.datap.ai"

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{tr['subject']}</title></head>
<body style="margin:0;padding:0;background:#f8f9fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f8f9fa;padding:40px 20px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

  <!-- Header with gradient -->
  <tr><td style="background:linear-gradient(135deg,#2e8b57,#3cb371);padding:40px 40px 30px;text-align:center;">
    <img src="{app_url}/logos/datapai.png" alt="DataPAI" width="160" style="margin-bottom:20px;" />
    <div style="display:inline-block;background:linear-gradient(135deg,#f59e0b,#d97706);color:#fff;padding:8px 24px;border-radius:100px;font-size:14px;font-weight:700;letter-spacing:0.5px;margin-bottom:12px;">
      Early Supporter #{badge_number}
    </div>
    <h1 style="color:#ffffff;font-size:26px;margin:16px 0 0;font-weight:700;">{tr['greeting']}</h1>
  </td></tr>

  <!-- Badge message -->
  <tr><td style="padding:30px 40px 10px;text-align:center;">
    <p style="color:#374151;font-size:16px;line-height:1.6;margin:0;">
      {tr['badge_forever']}
    </p>
  </td></tr>

  <!-- Quick Start steps -->
  <tr><td style="padding:20px 40px 30px;">
    <h2 style="color:#1f2937;font-size:18px;margin:0 0 20px;text-align:center;">{tr['quick_start']}</h2>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="33%" style="text-align:center;padding:10px;">
          <div style="width:48px;height:48px;border-radius:50%;background:#f0fdf4;margin:0 auto 10px;line-height:48px;font-size:22px;">&#128269;</div>
          <div style="font-weight:600;color:#2e8b57;font-size:18px;margin-bottom:4px;">1</div>
          <div style="color:#6b7280;font-size:13px;">{tr['step1']}</div>
        </td>
        <td width="33%" style="text-align:center;padding:10px;">
          <div style="width:48px;height:48px;border-radius:50%;background:#fffbeb;margin:0 auto 10px;line-height:48px;font-size:22px;">&#11088;</div>
          <div style="font-weight:600;color:#d97706;font-size:18px;margin-bottom:4px;">2</div>
          <div style="color:#6b7280;font-size:13px;">{tr['step2']}</div>
        </td>
        <td width="33%" style="text-align:center;padding:10px;">
          <div style="width:48px;height:48px;border-radius:50%;background:#eff6ff;margin:0 auto 10px;line-height:48px;font-size:22px;">&#129302;</div>
          <div style="font-weight:600;color:#2563eb;font-size:18px;margin-bottom:4px;">3</div>
          <div style="color:#6b7280;font-size:13px;">{tr['step3']}</div>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- CTA button -->
  <tr><td style="padding:0 40px 35px;text-align:center;">
    <a href="{app_url}/watchlist" style="display:inline-block;background:linear-gradient(135deg,#2e8b57,#3cb371);color:#ffffff;padding:14px 40px;border-radius:10px;text-decoration:none;font-weight:700;font-size:16px;letter-spacing:0.3px;">
      {tr['cta']} &rarr;
    </a>
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#f9fafb;padding:24px 40px;text-align:center;border-top:1px solid #f3f4f6;">
    <p style="color:#9ca3af;font-size:12px;margin:0;line-height:1.5;">
      DataPAI by AWSME Pty Ltd &middot; Suite 2/200 Mona Vale Rd, St Ives NSW 2075<br/>
      Powered by <a href="https://tinyfish.ai" style="color:#2e8b57;text-decoration:none;">TinyFish</a> &amp; <a href="https://www.ag2.ai" style="color:#2e8b57;text-decoration:none;">ag2</a>
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def send_welcome_email(email: str, badge_number: int, lang: str = "en") -> bool:
    """
    Send welcome email via AWS SES. Returns True on success.
    Gracefully returns False if SES is not configured.
    """
    from_email = os.environ.get("DATAPAI_SES_FROM_EMAIL")
    region = os.environ.get("AWS_REGION", "ap-southeast-2")

    if not from_email:
        log.warning("DATAPAI_SES_FROM_EMAIL not set — skipping welcome email for %s", email)
        return False

    tr = EMAIL_TRANSLATIONS.get(lang, EMAIL_TRANSLATIONS["en"])
    subject = tr["subject"]
    html_body = build_html_email(badge_number, lang)

    try:
        import boto3
        ses = boto3.client("ses", region_name=region)
        ses.send_email(
            Source=from_email,
            Destination={"ToAddresses": [email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            },
        )
        log.info("Welcome email sent to %s (Early Supporter #%d, lang=%s)", email, badge_number, lang)
        return True
    except ImportError:
        log.warning("boto3 not installed — skipping welcome email for %s", email)
        return False
    except Exception as e:
        log.error("Failed to send welcome email to %s: %s", email, e)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send DataPAI welcome email")
    parser.add_argument("--email", required=True, help="Recipient email")
    parser.add_argument("--badge-number", type=int, required=True, help="Early Supporter badge number")
    parser.add_argument("--lang", default="en", help="Language code (en, zh, zh-TW, ja, ko, vi, th, ms)")
    args = parser.parse_args()

    success = send_welcome_email(args.email, args.badge_number, args.lang)
    sys.exit(0 if success else 1)
