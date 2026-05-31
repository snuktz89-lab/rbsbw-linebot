import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

# ==================== ตั้งค่าตรงนี้ ====================
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Group ID ของกลุ่มช่าง/เซฟตี้ (ใส่ทีหลังหลังจากได้ Group ID)
TECHNICIAN_GROUP_ID = os.environ.get("TECHNICIAN_GROUP_ID", "")
# ========================================================

# ตั้งค่า Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# ตั้งค่า LINE
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# คำที่บอทจะตอบสนอง
KEYWORDS = {
    "แอร์": ["แอร์เสีย", "แอร์ไม่เย็น", "ตรวจสอบแอร์", "แอร์"],
    "น้ำ": ["น้ำรั่ว", "น้ำหก", "พื้นเปียก" , "น้ำไม่ไหล"],
    "แก๊ส": ["แก๊สตก", "แก๊สรั่ว", "แก๊ส"],
    "ไฟฟ้า": ["ไฟดับ", "ไฟช็อต", "ไฟช๊อต"],
    "ช่าง": ["รบกวนให้ช่างเข้ามาดู", "ช่างเข้ามาดูหน่อย", "ให้ช่างเข้ามา"],
}

def detect_problem(text):
    """ตรวจสอบว่าข้อความมีคำปัญหาไหม"""
    for category, keywords in KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                return category, keyword
    return None, None

def get_emoji(category):
    """ได้ emoji ตามประเภทปัญหา"""
    emojis = {
        "แอร์": "🌬️",
        "น้ำ": "💧",
        "แก๊ส": "🔥",
        "ไฟฟ้า": "⚡",
        "ช่าง": "🔧",
    }
    return emojis.get(category, "🔧")

def ask_gemini(problem_text):
    """ถาม Gemini เพื่อให้คำแนะนำเบื้องต้น"""
    try:
        prompt = f"""คุณเป็นผู้ช่วยงานซ่อมบำรุงอาคาร มีการแจ้งปัญหาว่า: "{problem_text}"
        
กรุณาตอบสั้นๆ ภาษาไทย 1-2 ประโยค เพื่อแนะนำวิธีแก้ไขเบื้องต้นที่ผู้ใช้ทำได้เองก่อนช่างมาถึง
ตอบแบบสุภาพและเป็นมิตร"""
        response = model.generate_content(prompt)
        return response.text.strip()
    except:
        return "กรุณารอช่างเข้าตรวจสอบครับ"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    # ตอบเฉพาะกลุ่มหลักเท่านั้น
    if event.source.group_id == TECHNICIAN_GROUP_ID:
        return

    text = event.message.text
    user_id = event.source.user_id
    group_id = event.source.group_id
    print(f"GROUP ID: {group_id}", flush=True)

    category, keyword = detect_problem(text)
    if not category:
        return  # ไม่ตอบถ้าไม่มีคำปัญหา

    emoji = get_emoji(category)
    ai_tip = ask_gemini(text)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # ดึงชื่อผู้ส่ง
        try:
            profile = line_bot_api.get_group_member_profile(group_id, user_id)
            sender_name = profile.display_name
        except:
            sender_name = "สมาชิก"

        # ตอบกลับในกลุ่มหลัก
        reply_text = (
            f"{emoji} รับเรื่องแล้วครับ!\n"
            f"📋 ปัญหา: {text}\n"
            f"💡 เบื้องต้น: {ai_tip}\n"
            f"⏳ กำลังแจ้งทีมช่างครับ"
        )
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

        # แจ้งกลุ่มช่าง/เซฟตี้
        if TECHNICIAN_GROUP_ID:
            import datetime
            import pytz
            tz = pytz.timezone("Asia/Bangkok")
            now = datetime.datetime.now(tz).strftime("%d/%m/%Y %H:%M")
            tech_text = (
                f"🚨 แจ้งซ่อม!\n"
                f"{emoji} ประเภท: {category}\n"
                f"📝 รายละเอียด: {text}\n"
                f"👤 ผู้แจ้ง: {sender_name}\n"
                f"🕐 เวลา: {now}\n"
                f"📍 กรุณาตรวจสอบด่วนครับ"
            )
            line_bot_api.push_message(
                PushMessageRequest(
                    to=TECHNICIAN_GROUP_ID,
                    messages=[TextMessage(text=tech_text)]
                )
            )

@app.route("/", methods=["GET"])
def index():
    return "LINE Bot is running! 🤖"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
