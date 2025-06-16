# app/router.py
from fastapi import APIRouter, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
import os
from dotenv import load_dotenv
import requests
from PIL import Image
import io
import tempfile
import logging

# [Import ฟังก์ชันที่จำเป็นทั้งหมด]
from .line_utils import LineBot, generate_help_message
from .ocr_utils import (
    extract_text_from_image, 
    parse_payment_slip, 
    format_slip_summary,
    setup_google_sheets_client,
    log_to_google_sheet
)

# ตั้งค่า Logger
logger = logging.getLogger(__name__)

load_dotenv()

# ตั้งค่า LINE Bot
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise ValueError("กรุณาตั้งค่า LINE_CHANNEL_ACCESS_TOKEN และ LINE_CHANNEL_SECRET ใน .env file")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

router = APIRouter()

@router.post("/webhook")
async def webhook(request: Request):
    """รับ webhook จาก LINE"""
    try:
        signature = request.headers['X-Line-Signature']
        body = await request.body()
        handler.handle(body.decode('utf-8'), signature)
        return {"status": "success"}
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    """จัดการข้อความ"""
    try:
        user_message = event.message.text.lower()
        if user_message in ['hello', 'hi', 'สวัสดี', 'หวัดดี']:
            reply_text = """สวัสดีครับ! 👋

🤖 **AI Chat Assistant QR - LINE Bot**

📋 **คุณสามารถ:**
• ส่งรูปสลิปเงินมาให้อ่านข้อมูล
• ส่งรูป QR Code มาให้แปลงเป็นข้อความ
• ส่งรูปเอกสารมาให้แปลงเป็นข้อความ

📱 **วิธีใช้:**
แค่ส่งรูปมาเลย! ระบบจะอ่านและแยกข้อมูลให้อัตโนมัติ

🔥 พร้อมใช้งานแล้ว!"""
        elif user_message in ['help', 'ช่วย', 'ช่วยเหลือ']:
            reply_text = """🆘 **วิธีใช้งาน**

1️⃣ **ส่งรูปสลิปเงิน**
   • รองรับทุกธนาคาร
   • แยกข้อมูล: จำนวนเงิน, วันที่, เวลา, ธนาคาร

2️⃣ **ส่งรูป QR Code**
   • แปลงเป็นข้อความ
   • รองรับ QR Code ทุกประเภท

3️⃣ **ส่งรูปเอกสาร**
   • แปลงรูปเป็นข้อความ
   • รองรับภาษาไทย + อังกฤษ

💡 **เคล็ดลับ:** ถ่ายรูปให้ชัด แสงสว่างพอ เพื่อผลลัพธ์ที่ดีที่สุด"""
        else:
            reply_text = f"""ได้รับข้อความ: "{event.message.text}"

🤖 ขณะนี้ฉันสามารถ:
• อ่านรูปสลิปเงิน
• อ่าน QR Code  
• แปลงรูปเป็นข้อความ

📷 ลองส่งรูปมาดูครับ!"""
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    except Exception as e:
        logger.error(f"Error handling text message: {str(e)}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้ง")
        )

@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    """จัดการรูปภาพ"""
    temp_file_path = None
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
            for chunk in message_content.iter_content():
                temp_file.write(chunk)
            temp_file_path = temp_file.name
        
        extracted_text = extract_text_from_image(temp_file_path)
        
        if not extracted_text or len(extracted_text.strip()) < 3:
            reply_text = """😅 **ไม่สามารถอ่านข้อความได้**

🔍 **เคล็ดลับ:**
• ถ่ายรูปให้ชัดขึ้น
• แสงสว่างเพียงพอ  
• ข้อความไม่เอียงมาก
• ลองถ่ายใกล้ขึ้น

📷 ลองส่งรูปใหม่ดูครับ!"""
        else:
            parsed_data = parse_payment_slip(extracted_text)
            
            is_slip = parsed_data.get("amount") or any(kw in extracted_text for kw in ["จำนวนเงิน", "บาท", "THB", "Amount"])
            
            if is_slip:
                reply_text = format_slip_summary(parsed_data)
                
                try:
                    logger.info(">>> เป็นสลิป! กำลังเริ่มขั้นตอนการบันทึกลง Google Sheet...")
                    sheets_client = setup_google_sheets_client()
                    if sheets_client:
                        log_to_google_sheet(sheets_client, parsed_data)
                    else:
                        logger.error("!!! ข้ามการบันทึกข้อมูลลง Google Sheet เพราะเชื่อมต่อไม่ได้")
                except Exception as e:
                    logger.error(f"!!! เกิดข้อผิดพลาดร้ายแรงขณะบันทึกลง Sheet: {e}")
            else:
                reply_text = f"""📄 **ข้อความที่อ่านได้:**
                📝 **จำนวนตัวอักษร:** {len(extracted_text)} ตัว
🔤 **จำนวนบรรทัด:** {len(extracted_text.splitlines())} บรรทัด"""
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        
    except Exception as e:
        logger.error(f"Error handling image: {str(e)}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="เกิดข้อผิดพลาดในการประมวลผลรูปภาพ กรุณาลองใหม่อีกครั้ง")
        )
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)

webhook_router = router
