import easyocr
import re
from typing import Dict, Any, Optional, List, Tuple
import logging
from datetime import datetime
import os
import json
from PIL import Image, ImageFilter, ImageOps
import numpy as np

# --- (เพิ่มส่วนนี้) ส่วน Import สำหรับ Google Sheets ---
import gspread
from google.oauth2.service_account import Credentials
from google.api_core.exceptions import GoogleAPIError
# --- สิ้นสุดส่วนที่เพิ่ม ---


# --- การตั้งค่า Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
Image.ANTIALIAS = Image.Resampling.LANCZOS

# --- การโหลดโมเดล EasyOCR ---
try:
    logger.info("กำลังโหลดโมเดล EasyOCR...")
    reader = easyocr.Reader(['th', 'en'], gpu=False)
    logger.info("โหลดโมเดล EasyOCR สำเร็จ")
except Exception as e:
    logger.error(f"ไม่สามารถโหลดโมเดล EasyOCR ได้: {e}")
    reader = None


# --- กรุณาแก้ไขค่าในส่วนนี้ ---
# --- เปลี่ยนตรงนี้ด้วยนะ ---
SERVICE_ACCOUNT_FILE = 'lineoa-slip-bot-5f1fd41b48a8.json'
# <-- แก้เป็นชื่อไฟล์ JSON ของคุณ
GOOGLE_SHEET_ID = '1ZZesldpq6As9zo_GHgWXOvQFBme9ZgymAFL-yAL5wAc'  # <-- แก้เป็นชื่อไฟล์ Google Sheet ของคุณ
# --------------------------------
# --------------------------------

def setup_google_sheets_client():
    """
    ตั้งค่าและยืนยันตัวตนเพื่อเชื่อมต่อกับ Google Sheets API
    """
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file"
        ]
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        logger.info("เชื่อมต่อ Google Sheets API สำเร็จ")
        return client
    except FileNotFoundError:
        logger.error(f"ไม่พบไฟล์ Service Account ที่: '{SERVICE_ACCOUNT_FILE}'")
        return None
    except Exception as e:
        logger.error(f"เกิดข้อผิดพลาดในการเชื่อมต่อ Google Sheets API: {e}")
        return None

def log_to_google_sheet(client: gspread.Client, data: Dict[str, Any]):
    """
    บันทึกข้อมูลที่แยกวิเคราะห์ได้ลงในแถวใหม่ของ Google Sheet
    """
    if not client:
        logger.error("ไม่สามารถบันทึกข้อมูลได้เนื่องจาก client ของ Google Sheets ไม่ถูกต้อง")
        return

    try:
        logger.info(f"กำลังเปิด Google Sheet ด้วย ID: '{GOOGLE_SHEET_ID}'...")
        # ใช้ ID ในการเปิดชีท ซึ่งเป็นวิธีที่แม่นยำที่สุด
        sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

        # ตรวจสอบ Header และเพิ่มถ้ายังไม่มี
        # (แก้ไขเล็กน้อยเพื่อป้องกัน error ถ้าชีทว่างเปล่า تماماً)
        try:
            header_row = sheet.row_values(1)
        except gspread.exceptions.APIError:
            header_row = [] # กรณีชีทใหม่และว่างเปล่าจริงๆ

        header = ["Timestamp", "Date", "Time", "Amount", "Sender", "Recipient", "Bank", "Reference"]
        if header_row != header:
            # ตรวจสอบว่าแถวที่ 1 ว่างหรือไม่ก่อนเขียน Header
            if not header_row:
                sheet.update(f'A1:H1', [header])
                logger.info("เพิ่ม Header ใน Google Sheet เรียบร้อยแล้ว")

        # เตรียมข้อมูลสำหรับบันทึก (เรียงตาม Header)
        row_to_insert = [
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            data.get('date', '-'),
            data.get('time', '-'),
            data.get('amount', '-'),
            data.get('sender', '-'),
            data.get('recipient', '-'),
            data.get('bank', '-'),
            data.get('reference', '-')
        ]

        sheet.append_row(row_to_insert)
        logger.info("✅ บันทึกข้อมูลลง Google Sheet สำเร็จ!")

    except gspread.exceptions.SpreadsheetNotFound:
        # Error นี้ไม่ควรจะเกิดขึ้นแล้วเมื่อเราใช้ ID
        logger.error(f"❌ ไม่พบ Google Sheet ที่มี ID: '{GOOGLE_SHEET_ID}'")
    except GoogleAPIError as e:
        logger.error(f"❌ เกิดข้อผิดพลาดจาก Google API: {e} - (อาจเกิดจากยังไม่ได้แชร์ชีทให้ Editor)")
    except Exception as e:
        logger.error(f"❌ เกิดข้อผิดพลาดที่ไม่คาดคิดขณะบันทึกข้อมูลลง Google Sheet: {e}")
# --- สิ้นสุดส่วนที่เพิ่ม ---


def extract_text_from_image(image_path: str) -> Optional[str]:
    """
    ดึงข้อความทั้งหมดจากรูปภาพโดยใช้ EasyOCR
    ฟังก์ชันนี้จะคืนค่าข้อความทั้งหมดที่พบในรูปภาพเป็นสตริงเดียว
    """
    if not reader:
        logger.error("EasyOCR reader ไม่ได้ถูกโหลดอย่างถูกต้อง")
        return None
    try:
        logger.info(f"กำลังอ่านข้อความจากรูปภาพ: {image_path}")
        # ตั้งค่า y_ths และ x_ths เพื่อช่วยให้การรวมย่อหน้าดีขึ้น
        results = reader.readtext(image_path, detail=0, paragraph=True, y_ths=-0.05, x_ths=1.2)
        extracted_text = "\n".join(results)
        logger.info(f"การดึงข้อความสำเร็จ: พบ {len(extracted_text)} ตัวอักษร")
        return extracted_text.strip()
    except FileNotFoundError:
        logger.error(f"ไม่พบไฟล์ที่: {image_path}")
        return None
    except Exception as e:
        logger.error(f"เกิดข้อผิดพลาดขณะอ่านรูปภาพด้วย EasyOCR: {str(e)}")
        return None

# --- ฟังก์ชันช่วย (Helper Functions) ---
def find_first_match(text: str, patterns: List[str]) -> Optional[str]:
    """
    ค้นหาข้อความจากรายการรูปแบบ Regular Expression และคืนค่ากลุ่มที่จับคู่ได้กลุ่มแรกที่พบ
    """
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            for group in match.groups():
                if group:
                    return group.strip()
    return None

def _find_date(text: str) -> Optional[str]:
    """
    ค้นหาและแปลง 'วันที่' โดยเน้นรูปแบบ 'วัน เดือน ปี' เพื่อความแม่นยำที่ดีขึ้น
    เวอร์ชันใหม่นี้ใช้กลยุทธ์ 2 ขั้นตอนที่แข็งแกร่งกว่า:
    1. ค้นหาคู่ของเดือนและปี
    2. ค้นหาย้อนหลังจากจุดนั้นเพื่อหาวันที่มีความเป็นไปได้มากที่สุด
    ** เพิ่ม: รองรับกรณีวันที่แยกบรรทัด (เช่น SCB) **
    """
    parse_thai_months = {
        'มกราคม': 1, 'กุมภาพันธ์': 2, 'มีนาคม': 3, 'เมษายน': 4, 'พฤษภาคม': 5, 'มิถุนายน': 6,
        'กรกฎาคม': 7, 'สิงหาคม': 8, 'กันยายน': 9, 'ตุลาคม': 10, 'พฤศจิกายน': 11, 'ธันวาคม': 12,
        'ม.ค.': 1, 'ก.พ.': 2, 'มี.ค.': 3, 'เม.ย.': 4, 'พ.ค.': 5, 'มิ.ย.': 6,
        'ก.ค.': 7, 'ส.ค.': 8, 'ก.ย.': 9, 'ต.ค.': 10, 'พ.ย.': 11, 'ธ.ค.': 12
    }

    # --- ลำดับที่ 1: ลองจับวันที่แยกบรรทัด (SCB) ก่อน ---
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    logger.info(f"แยกข้อความเป็น {len(lines)} บรรทัด")
    for i, line in enumerate(lines):
        # Debug: แสดงบรรทัดที่กำลังตรวจสอบ
        logger.info(f"ตรวจสอบบรรทัด {i}: '{line}' (ความยาว: {len(line)} ตัวอักษร)")
        # Pattern ที่แก้ไขแล้ว - รองรับทั้ง "พ.ค" และ "พ.ค."
        day_month_pattern = r'(\d{1,2})\s*(ม\.ค\.?|ก\.พ\.?|มี\.ค\.?|เม\.ย\.?|พ\.ค\.?|มิ\.ย\.?|ก\.ค\.?|ส\.ค\.?|ก\.ย\.?|ต\.ค\.?|พ\.ย\.?|ธ\.ค\.?)'
        day_month_match = re.search(day_month_pattern, line.strip(), re.IGNORECASE)
        if day_month_match:
            logger.info(f"✅ พบ pattern วัน+เดือน ในบรรทัด {i}: '{line}'")
            if i+1 < len(lines):
                next_line = lines[i+1].strip()
                logger.info(f"ตรวจสอบบรรทัดถัดไป {i+1}: '{next_line}' (ความยาว: {len(next_line)} ตัวอักษร)")
                # Pattern สำหรับ "2568 20:09" (ปี + เวลา)
                year_time_pattern = r'(\d{4})\s+\d{1,2}:\d{2}'
                year_time_match = re.search(year_time_pattern, next_line)
                if year_time_match:
                    day = int(day_month_match.group(1))
                    month_abbr = day_month_match.group(2)
                    year_be = int(year_time_match.group(1))
                    # เพิ่มจุดให้เดือนที่ไม่มีจุด (เพื่อให้ map ได้)
                    if not month_abbr.endswith('.'):
                        month_abbr += '.'
                    # แปลงเดือนย่อเป็นชื่อเต็ม
                    month_full_map = {
                        "ม.ค.": "มกราคม", "ก.พ.": "กุมภาพันธ์", "มี.ค.": "มีนาคม", "เม.ย.": "เมษายน",
                        "พ.ค.": "พฤษภาคม", "มิ.ย.": "มิถุนายน", "ก.ค.": "กรกฎาคม", "ส.ค.": "สิงหาคม",
                        "ก.ย.": "กันยายน", "ต.ค.": "ตุลาคม", "พ.ย.": "พฤศจิกายน", "ธ.ค.": "ธันวาคม"
                    }
                    month_full = month_full_map.get(month_abbr, month_abbr)
                    logger.info(f"✅ พบวันที่แยกบรรทัด (SCB): วัน={day}, เดือน={month_full}, ปี={year_be}")
                    return f"{day} {month_full} {year_be}"
                else:
                    logger.info(f"❌ บรรทัดถัดไปไม่ตรง pattern ปี+เวลา: '{next_line}'")
            else:
                logger.info(f"❌ ไม่มีบรรทัดถัดไป")
        else:
            # Debug เพิ่มเติม: ทดสอบ pattern ทีละส่วน
            if re.search(r'\d{1,2}', line):
                logger.info(f"⚠️ บรรทัด {i} มีตัวเลข แต่ไม่ match pattern เต็ม")
            if re.search(r'พ\.ค\.?', line, re.IGNORECASE):
                logger.info(f"⚠️ บรรทัด {i} มี 'พ.ค.' แต่ไม่ match pattern เต็ม")

    # --- ลำดับที่ 2: ลองหาวันที่ในบรรทัดเดียวกัน (รูปแบบปกติ) ---
    logger.info("ไม่พบรูปแบบ SCB, ลองค้นหารูปแบบปกติ...")
    month_keys = [re.escape(k) for k in parse_thai_months.keys()]
    months_pattern_str = '|'.join(month_keys)
    # ขั้นตอนที่ 1: ค้นหาคู่เดือน-ปีก่อน
    month_year_pattern = re.compile(
        r'(' + months_pattern_str + r')'
        r'[\s/.-]+'
        r'(\d{2,4})',
        re.IGNORECASE
    )
    month_year_match = month_year_pattern.search(text)
    day_str, month_str, year_str = None, None, None
    if not month_year_match:
        # กรณีสำรองสำหรับวันที่เป็นตัวเลขล้วนหากกลยุทธ์หลักล้มเหลว
        numeric_match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', text)
        if not numeric_match:
            logger.warning("ไม่พบรูปแบบวันที่ที่ตรงกันในข้อความ")
            return None
        day_str, month_str, year_str = numeric_match.groups()
    else:
        month_str, year_str = month_year_match.groups()
        # ขั้นตอนที่ 2: ค้นหาย้อนหลังจากเดือน-ปีเพื่อหาวัน
        text_before_month = text[:month_year_match.start()]
        # ค้นหาตัวเลข 1 หรือ 2 หลักทั้งหมดในข้อความก่อนหน้า
        possible_days = re.findall(r'\b(\d{1,2})\b', text_before_month)
        if not possible_days:
            logger.warning("พบเดือน/ปี แต่ไม่พบวันก่อนหน้า")
            return None
        # ตัวเลขสุดท้ายที่พบคือตัวเลือกที่เป็นไปได้มากที่สุดสำหรับวัน
        day_str = possible_days[-1]
        logger.info(f"พบองค์ประกอบของวันที่: วัน='{day_str}', เดือน='{month_str}', ปี='{year_str}'")

    try:
        day = int(day_str)
        year_be = int(year_str)
        if len(year_str) <= 2:
            current_year_be = datetime.now().year + 543
            century = (current_year_be // 100) * 100
            year_be += century
        year_ad = year_be - 543 if year_be > 2500 else year_be
        month_num = None
        try:
            month_num = int(month_str)
        except ValueError:
            for th_month_key, num in parse_thai_months.items():
                if th_month_key.lower() in month_str.lower():
                    month_num = num
                    break
        if month_num is None:
            raise ValueError(f"ไม่สามารถแยกวิเคราะห์เดือนได้: {month_str}")
        if not (1 <= day <= 31 and 1 <= month_num <= 12):
            raise ValueError(f"ค่าวันหรือเดือนไม่ถูกต้อง: วัน={day}, เดือน={month_num}")
        date_obj = datetime(year_ad, month_num, day)
        full_thai_months = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
        month_name_full = full_thai_months[date_obj.month - 1]
        formatted_date = f"{day} {month_name_full} {year_be}"
        return formatted_date
    except Exception as e:
        logger.error(f"เกิดข้อผิดพลาดในการแปลงองค์ประกอบของวันที่: {e}")
        return f"{day_str} {month_str} {year_str}" if all([day_str, month_str, year_str]) else None

def _find_time(text: str) -> Optional[str]:
    """ค้นหา 'เวลา' และคืนค่าในรูปแบบ HH:MM หรือ HH:MM:SS"""
    time_on_date_line = re.search(r'\d{1,2}\s+[ก-ฮเ-์.]+\s+\d{2,4}[,\s]+(\d{1,2}:\d{2}(?::\d{2})?)', text, re.IGNORECASE)
    if time_on_date_line:
        return time_on_date_line.group(1)
    time_patterns = [
        r'(?:เวลา|Time)\s*[:\s]*(\d{2}:\d{2}(?::\d{2})?)',
        r'\b(\d{2}:\d{2}:\d{2})\b',
        r'\b(\d{1,2}:\d{2})\b'
    ]
    time_str = find_first_match(text, time_patterns)
    return time_str

def _parse_amount(text: str) -> Optional[str]:
    """ค้นหาจำนวนเงินในรูปแบบ x,xxx.xx"""
    patterns = [
        r'(?:จำนวนเงิน|Amount|โอนเงินสำเร็จ|ยอดเงิน|จำนวน\s?เงิน)\s*[:\s]*([\d,]+\.\d{2})',
        r'([\d,]+\.\d{2})\s*(?:บาท|BAHT|thb)',
        r'\b([\d,]{1,10}\.\d{2})\b'
    ]
    amount = find_first_match(text, patterns)
    return amount.replace(',', '') if amount else None

def _clean_ocr_name(name: Optional[str]) -> Optional[str]:
    """ทำความสะอาดชื่อที่ได้จาก OCR โดยลบสัญลักษณ์และข้อความที่ไม่ต้องการ"""
    if not name:
        return None
    # ลบอักขระพิเศษและช่องว่างด้านหน้า
    cleaned = re.sub(r'^[.\s]+', '', name)
    cleaned = cleaned.replace('ฺ', '')
    cleaned = re.sub(r'^[.\sาอ]+', '', cleaned).strip()
    # ลบชื่อธนาคารที่ติดมากับชื่อ (ทั้งด้านหน้าและด้านหลัง)
    bank_codes = [
        'ttb', 'TTB', 'scb', 'SCB', 'ktb', 'KTB', 'bbl', 'BBL',
        'kbank', 'KBANK', 'bay', 'BAY', 'gsb', 'GSB', 'baac', 'BAAC',
        'ธนาคารกรุงเทพ', 'ธนาคารไทยพาณิชย์', 'ธนาคารกรุงไทย',
        'ธนาคารกสิกรไทย', 'ธนาคารทหารไทยธนชาต', 'ธนาคารออมสิน'
    ]
    # สร้าง pattern เพื่อลบชื่อธนาคารทั้งด้านหน้าและหลัง
    bank_pattern = '|'.join([re.escape(code) for code in bank_codes])
    # ลบชื่อธนาคารที่อยู่ด้านหน้าหรือด้านหลังชื่อ (พร้อมช่องว่างที่ติดมา)
    cleaned = re.sub(fr'\s*({bank_pattern})\s*', ' ', cleaned, flags=re.IGNORECASE)
    # ลบช่องว่างหลายตัวติดกันให้เหลือแค่ช่องว่างเดียว
    cleaned = re.sub(r'\s+', ' ', cleaned)
    # ลบช่องว่างที่ด้านหน้าและหลัง
    cleaned = cleaned.strip()
    # ลบเลขบัญชีที่อาจติดมา (เช่น xxx-x-xx960-1)
    cleaned = re.sub(r'\s*x+[-x\d]*\s*', '', cleaned, flags=re.IGNORECASE)
    return cleaned if cleaned else None

def _find_standalone_name(text: str, context_keywords: List[str]) -> Optional[str]:
    """ค้นหาชื่อที่อาจจะอยู่บนบรรทัดของตัวเอง โดยใช้คำสำคัญจากบรรทัดก่อนหน้าเป็นบริบท"""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    for i, line in enumerate(lines):
        name_match = re.match(r'^((?:นาย|นาง|นางสาว|น\.ส\.|คุณ|บจก\.|หจก\.)?\s*[ก-๙A-Za-z\s.\'"]+)', line, re.IGNORECASE)
        if name_match:
            if i > 0:
                previous_line = lines[i-1].upper()
                if any(kw.upper() in previous_line for kw in context_keywords):
                    name = name_match.group(1).strip()
                    return re.sub(r'\s*x-?[\dx]+.*', '', name).strip()
    return None

def _parse_name(text: str, keywords: List[str]) -> Optional[str]:
    """ค้นหาชื่อบุคคล/บริษัทจากคำสำคัญที่ระบุ (เช่น จาก, ถึง)"""
    all_keywords = '|'.join(keywords)
    patterns = [
        fr'(?:{all_keywords})[\s:.-]*((?:นาย|นาง|นางสาว|น\.ส\.|คุณ|บจก\.|หจก\.)?\s*[ก-๙A-Za-z\s.\'"]+?)(?=\s*x-?[\dx]+|\s*ธนาคาร|$)',
        fr'(?:{all_keywords})\s+((?:นาย|นาง|นางสาว|น\.ส\.|คุณ|บจก\.|หจก\.)?\s*[ก-๙A-Za-z\s.\'"]+)'
    ]
    name = find_first_match(text, patterns)
    if name:
        cleaned_name = re.sub(r'[\d\s-]+$', '', name).strip()
        cleaned_name = re.sub(fr'({all_keywords})', '', cleaned_name, flags=re.IGNORECASE).strip()
        if cleaned_name and cleaned_name.lower() not in ['นาย', 'นาง', 'นางสาว', 'น.ส.', 'คุณ']:
            return cleaned_name
    return None

def _find_names_by_account_number(text: str) -> List[str]:
    """ค้นหาชื่อโดยใช้ตำแหน่งที่สัมพันธ์กับหมายเลขบัญชีธนาคาร"""
    found_names = []
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    account_pattern = re.compile(r'(\b\d{10}\b|x-?[\dx-]{5,})', re.IGNORECASE)
    name_pattern = re.compile(r'^((?:นาย|นาง|นางสาว|น\.ส\.|คุณ|บจก\.|หจก\.)?\s*[ก-๙A-Za-z\s.\'"]+)', re.IGNORECASE)
    non_name_clues = re.compile(r'(ธนาคาร|bank|\bธ\.|\bธ\s|โอนเงิน|จำนวนเงิน|วันที่|สำเร็จ|บาท|baht|amount|transfer)', re.IGNORECASE)
    for i, line in enumerate(lines):
        name_match = name_pattern.match(line)
        if name_match and not non_name_clues.search(line):
            name_confirmed = False
            if account_pattern.search(line):
                name_confirmed = True
            if not name_confirmed and i + 1 < len(lines):
                if account_pattern.search(lines[i+1]):
                    name_confirmed = True
            if not name_confirmed and i + 2 < len(lines):
                if non_name_clues.search(lines[i+1]) and account_pattern.search(lines[i+2]):
                    name_confirmed = True
            if name_confirmed:
                name = name_match.group(1).strip()
                if re.fullmatch(r'[\sx-]+', name, re.IGNORECASE):
                    continue
                name = re.sub(r'\s+x-?[\dx-]+.*', '', name, flags=re.IGNORECASE).strip()
                if len(name) > 2 and name not in found_names:
                    found_names.append(name)
                    logger.info(f"ยืนยันชื่อ '{name}' จากบริบทแล้ว")
    logger.info(f"ชื่อสุดท้ายที่พบตามตำแหน่ง: {found_names}")
    return found_names

def parse_payment_slip(text: str) -> Dict[str, Any]:
    if not text:
        return {"error": "ไม่มีข้อความให้"}
    parsed_data = {"raw_text": text}
    # 1. ค้นหาธนาคาร (ปรับลำดับและ keywords ใหม่)
    bank_keywords = {
        "ทหารไทยธนชาต": ["TTB", "ttb", "TMBTHANACHART BANK", "ธนาคารทหารไทยธนชาต", "ทีเอ็มบีธนชาต", "ทหารไทย", "ธนชาต", "TTMB", "ub"],
        "ไทยพาณิชย์": ["SCB", "SIAM COMMERCIAL BANK", "ธนาคารไทยพาณิชย์", "ไทยพาณิชย์"],
        "กรุงไทย": ["KTB", "KRUNGTHAI", "krungthai", "ธนาคารกรุงไทย", "กรุงไทย", "ก ร ง ไท ย"],
        "กรุงเทพ": ["BBL", "BBLA", "BANGKOK BANK", "ธนาคารกรุงเทพ", "กรุงเทพ"],
        "กสิกรไทย": ["KBANK", "KASIKORNBANK", "KASI", "KPLUS", "K+", "+", "MAKE", "MAKE by KBank", "ธนาคารกสิกรไทย", "กสิกรไทย", "กสิกร", "ร.กสิกรไทย", "ภ ส ก ร ไท ย"],
        "ออมสิน": ["GSB", "GOVERNMENT SAVINGS BANK", "MYMO", "ธนาคารออมสิน", "ออมสิน", "อ อ ม ส น"],
        "กรุงศรีอยุธยา": ["BAY", "KRUNGSRI", "BANK OF AYUDHYA", "ธนาคารกรุงศรีอยุธยา", "กรุงศรี"],
        "ธ.ก.ส.": ["BAAC", "ธกส", "ธ.ก.ส."],
    }
    parsed_data["bank"] = None
    text_upper = text.upper()
    recipient_markers = ['ไปยัง', 'ไปที่', 'TO', 'ผู้รับเงิน', 'ผู้รับ', 'RECIPIENT', 'ถึง']
    recipient_pattern = '|'.join(recipient_markers)
    match = re.search(recipient_pattern, text, re.IGNORECASE)
    # แบ่งข้อความเป็นส่วนผู้ส่งและส่วนผู้รับ
    sender_section_text = text_upper
    recipient_section_text = ""
    if match:
        sender_section_text = text_upper[:match.start()]
        recipient_section_text = text_upper[match.start():]
        logger.info(f"พบเครื่องหมายผู้รับ '{match.group(0)}' กำลังวิเคราะห์ข้อความก่อนหน้านี้เพื่อหาธนาคารของผู้ส่ง")
    else:
        logger.info("ไม่พบเครื่องหมายผู้รับ กำลังวิเคราะห์ข้อความทั้งหมดเพื่อหาธนาคารของผู้ส่ง")
    # ค้นหาธนาคารจากส่วนผู้ส่งก่อน (ลำดับสำคัญ: TTB > SCB > อื่นๆ)
    sender_bank = None
    for name, kw_list in bank_keywords.items():
        # ให้ TTB มีความสำคัญสูงสุด
        if name == "ทหารไทยธนชาต":
            ttb_pattern = r'\b(TTB|ttb)\b'  # ใช้ word boundary เพื่อให้แม่นยำ
            if re.search(ttb_pattern, sender_section_text):
                sender_bank = name
                logger.info(f"พบธนาคาร TTB ในส่วนของผู้ส่ง: {sender_bank}")
                break
        else:
            bank_pattern = '|'.join([re.escape(kw) for kw in kw_list])
            if re.search(bank_pattern, sender_section_text):
                sender_bank = name
                logger.info(f"พบธนาคารในส่วนของผู้ส่ง: {sender_bank}")
                break
    # ถ้าไม่พบในส่วนผู้ส่ง ลองค้นหาทั่วไป (แต่ให้ TTB มีความสำคัญ)
    if not sender_bank:
        logger.warning("ไม่พบธนาคารในส่วนของผู้ส่ง กำลังทำการค้นหาทั่วไปในข้อความทั้งหมด")
        # ตรวจสอบ TTB ก่อน
        if re.search(r'\b(TTB|ttb)\b', text_upper):
            sender_bank = "ทหารไทยธนชาต"
            logger.info(f"พบธนาคาร TTB ในการค้นหาทั่วไป: {sender_bank}")
        else:
            # ถ้าไม่มี TTB ค่อยตรวจสอบธนาคารอื่น
            for name, kw_list in bank_keywords.items():
                if name != "ทหารไทยธนชาต":  # ข้าม TTB เพราะตรวจแล้ว
                    bank_pattern = '|'.join([re.escape(kw) for kw in kw_list])
                    if re.search(bank_pattern, text_upper):
                        sender_bank = name
                        logger.info(f"พบธนาคารในการค้นหาทั่วไป: {sender_bank}")
                        break
    parsed_data["bank"] = sender_bank
    # 2. ค้นหารหัสอ้างอิงและวันที่ (ปรับปรุงสำหรับ GSB)
    ref_patterns = [
        # รูปแบบ GSB/mymo: รหัสอ้างอิง: . 30 6120.6752937/06:000889790 เม.ย. 2568
        r'รหัสอ้างอิง[:.\s]*(\d{1,2})\s+([A-Za-z0-9./:]+)\s+(ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.|มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม)\s+(\d{4})',
        # รูปแบบปกติ: รหัสอ้างอิง: XXXXXXXXX
        r'รหัสอ้างอิง[:.\s]*([A-Z0-9]{10,})',
        # รูปแบบอื่นๆ
        r'(?:รหัสอ้างอิง|หมายเลขอ้างอิง|เลขที่อ้างอิง)[\s:.]*([a-zA-Z0-9\s-]+)',
        r'\b([a-zA-Z0-9]{15,})\b'
    ]
    parsed_data["reference"] = None
    parsed_data["date"] = None
    for pattern in ref_patterns:
        match = re.search(pattern, text)
        if match:
            if len(match.groups()) == 1:
                # รูปแบบปกติ
                parsed_data["reference"] = match.group(1).strip().replace(" ", "")
                break
            elif len(match.groups()) == 4:
                # รูปแบบ GSB: วัน + reference + เดือน + ปี
                day, reference, month, year = match.groups()
                parsed_data["reference"] = reference.replace(" ", "")
                parsed_data["date"] = f"{int(day)} {month} {year}"
                break
    # 3. ค้นหาวันที่ (ถ้ายังไม่ได้จาก ref_patterns)
    if not parsed_data["date"]:
        parsed_data["date"] = _find_date(text)
    # 4. ข้อมูลอื่นๆ
    parsed_data["amount"] = _parse_amount(text)
    parsed_data["time"] = _find_time(text)
    sender_keywords = ['จาก', 'From', 'ผู้โอน']
    recipient_keywords = ['ไปยัง','ไปที่', 'To', 'ผู้รับเงิน', 'ผู้รับ', 'Recipient', 'ถึง']
    sender = _parse_name(text, sender_keywords) or _find_standalone_name(text, sender_keywords)
    recipient = _parse_name(text, recipient_keywords) or _find_standalone_name(text, recipient_keywords)
    if not sender or not recipient:
        names_from_position = _find_names_by_account_number(text)
        if not sender and len(names_from_position) >= 1:
            sender = names_from_position[0]
        if not recipient and len(names_from_position) >= 2:
            recipient = names_from_position[1]
    parsed_data["sender"] = _clean_ocr_name(sender)
    parsed_data["recipient"] = _clean_ocr_name(recipient)
    logger.info("การแยกวิเคราะห์ข้อมูลสลิปเสร็จสมบูรณ์")
    return parsed_data

def format_slip_summary(data: Dict[str, Any]) -> str:
    """
    จัดรูปแบบข้อมูลที่แยกวิเคราะห์ได้ให้เป็นสรุปที่อ่านง่าย
    *** โค้ดส่วนนี้คือส่วนที่แก้ไขการย่อหน้า ***
    """
    if "error" in data:
        return f"❌ ไม่สามารถสร้างสรุปได้: {data['error']}"
    summary = ["📄 สรุปข้อมูลการทำรายการ"]
    summary.append("-" * 30)
    summary.append("\n--- ข้อมูลผู้ทำรายการ ---")
    summary.append(f"👤 จาก: {data.get('sender') or '-'}")
    summary.append(f"👥 ไปยัง: {data.get('recipient') or '-'}")
    summary.append("\n--- รายละเอียดธุรกรรม ---")
    if data.get("bank"):
        summary.append(f"🏦 ธนาคาร: {data['bank']}")
    if data.get("amount"):
        try:
            amount_num = float(data["amount"])
            summary.append(f"💰 จำนวนเงิน: {amount_num:,.2f} บาท")
        except (ValueError, TypeError):
            summary.append(f"💰 จำนวนเงิน: {data.get('amount', '-')} บาท")
    if data.get("date"):
        summary.append(f"📅 วันที่: {data['date']}")
    if data.get("time"):
        summary.append(f"⏰ เวลา: {data['time']} น.")
    if data.get("reference"):
        summary.append(f"🔢 เลขที่อ้างอิง: {data['reference']}")
    raw_text = data.get('raw_text', 'ไม่มีข้อมูล')

    summary.append("\n" + "-" * 30)
    summary.append(f"(สร้างเมื่อ: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')})")
    return "\n".join(summary)

# --- ส่วนการทำงานหลักของโปรแกรม ---
if __name__ == "__main__":
    # <<<<<<<<---- ใส่ชื่อไฟล์รูปภาพสลิปของคุณที่นี่
    image_path = "S__67641364.jpg" 
    
    if not os.path.exists(image_path):
        print(f"❌ ข้อผิดพลาด: ไม่พบไฟล์ที่ '{image_path}' โปรดตรวจสอบว่าไฟล์มีอยู่จริงและพาธถูกต้อง")
    else:
        print("-" * 50)
        # 1. ดึงข้อความจากรูปภาพ
        raw_text = extract_text_from_image(image_path)
        if raw_text:
            # 2. แยกวิเคราะห์ข้อมูลจากข้อความดิบ
            parsed_data = parse_payment_slip(raw_text)
            # 3. สร้างสรุปจากข้อมูลที่แยกวิเคราะห์แล้ว
            summary = format_slip_summary(parsed_data)
            # --- แสดงผลลัพธ์ ---
            print("\n[+] ผลการวิเคราะห์ข้อมูล:\n")
            print(summary)
            print("-" * 50)
            print("\n[+] ข้อมูลที่แยกวิเคราะห์ในรูปแบบ JSON:\n")
            # ไม่แสดง raw_text ใน JSON เพื่อความกระชับ
            data_to_show = {k: v for k, v in parsed_data.items() if k != 'raw_text'}
            print(json.dumps(data_to_show, indent=4, ensure_ascii=False))

            # --- (เพิ่มส่วนนี้) ส่วนเรียกใช้ฟังก์ชันบันทึกลง Google Sheet ---
            print("-" * 50)
            sheets_client = setup_google_sheets_client()
            if sheets_client:
                log_to_google_sheet(sheets_client, parsed_data)
            else:
                print("\nข้ามการบันทึกข้อมูลลง Google Sheet เนื่องจากเกิดข้อผิดพลาดในการเชื่อมต่อ")
            # --- สิ้นสุดส่วนที่เพิ่ม ---

        else:
            print(f"\nไม่สามารถประมวลผลรูปภาพ '{image_path}' ได้")
