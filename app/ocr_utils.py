import easyocr
import re
from typing import Dict, Any, Optional, List, Tuple
import logging
from datetime import datetime
import os
import json

# --- การตั้งค่า Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- การโหลดโมเดล EasyOCR ---
# พยายามโหลดโมเดล OCR สำหรับภาษาไทยและภาษาอังกฤษ
try:
    logger.info("กำลังโหลดโมเดล EasyOCR...")
    # ตั้งค่า gpu=False หากไม่ได้ใช้ GPU
    reader = easyocr.Reader(['th', 'en'], gpu=False)
    logger.info("โหลดโมเดล EasyOCR สำเร็จ")
except Exception as e:
    logger.error(f"ไม่สามารถโหลดโมเดล EasyOCR ได้: {e}")
    reader = None


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
    """
    parse_thai_months = {
        'มกราคม': 1, 'กุมภาพันธ์': 2, 'มีนาคม': 3, 'เมษายน': 4, 'พฤษภาคม': 5, 'มิถุนายน': 6,
        'กรกฎาคม': 7, 'สิงหาคม': 8, 'กันยายน': 9, 'ตุลาคม': 10, 'พฤศจิกายน': 11, 'ธันวาคม': 12,
        'ม.ค.': 1, 'ก.พ.': 2, 'มี.ค.': 3, 'เม.ย.': 4, 'พ.ค.': 5, 'มิ.ย.': 6,
        'ก.ค.': 7, 'ส.ค.': 8, 'ก.ย.': 9, 'ต.ค.': 10, 'พ.ย.': 11, 'ธ.ค.': 12
    }

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
    if not name:
        return None
    cleaned = re.sub(r'^[.\s]+', '', name)
    cleaned = cleaned.replace('ฺ', '')
    cleaned = re.sub(r'^[.\sาอ]+', '', cleaned).strip()
    return cleaned.strip()

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

    # 1. ค้นหาธนาคาร
    bank_keywords = {
       "กรุงเทพ": ["BBL", "BBLA", "BANGKOK BANK", "ธนาคารกรุงเทพ", "กรุงเทพ"],
       "กสิกรไทย": ["KBANK", "KASIKORNBANK", "KASI", "KPLUS", "K+", "+", "MAKE", "MAKE by KBank", "ธนาคารกสิกรไทย", "กสิกรไทย", "กสิกร", "ร.กสิกรไทย", "ภ ส ก ร ไท ย"],
       "ไทยพาณิชย์": ["SCB", "SIAM COMMERCIAL BANK", "ธนาคารไทยพาณิชย์", "ไทยพาณิชย์"],
       "กรุงไทย": ["KTB", "KRUNGTHAI", "krungthai", "ธนาคารกรุงไทย", "กรุงไทย", "ก ร ง ไท ย"],
       "ทหารไทยธนชาต": ["TTB", "ttb", "TMBTHANACHART BANK", "ธนาคารทหารไทยธนชาต", "ทีเอ็มบีธนชาต", "ทหารไทย", "ธนชาต", "TTMB"],
       "ออมสิน": ["GSB", "GOVERNMENT SAVINGS BANK", "MYMO", "ธนาคารออมสิน", "ออมสิน", "อ อ ม ส น"],
       "กรุงศรีอยุธยา": ["BAY", "KRUNGSRI", "BANK OF AYUDHYA", "ธนาคารกรุงศรีอยุธยา", "กรุงศรี"],
       "ธ.ก.ส.": ["BAAC", "ธกส", "ธ.ก.ส."],
    }
    
    parsed_data["bank"] = None
    text_upper = text.upper()
    recipient_markers = ['ไปยัง', 'ไปที่', 'TO', 'ผู้รับเงิน', 'ผู้รับ', 'RECIPIENT', 'ถึง']
    recipient_pattern = '|'.join(recipient_markers)
    match = re.search(recipient_pattern, text, re.IGNORECASE)

    sender_section_text = text_upper
    if match:
        sender_section_text = text_upper[:match.start()]
        logger.info(f"พบเครื่องหมายผู้รับ '{match.group(0)}' กำลังวิเคราะห์ข้อความก่อนหน้านี้เพื่อหาธนาคารของผู้ส่ง")
    else:
        logger.info("ไม่พบเครื่องหมายผู้รับ กำลังวิเคราะห์ข้อความทั้งหมดเพื่อหาธนาคารของผู้ส่ง")

    sender_bank = None
    for name, kw_list in bank_keywords.items():
        bank_pattern = '|'.join([re.escape(kw) for kw in kw_list])
        if re.search(bank_pattern, sender_section_text):
            sender_bank = name
            logger.info(f"พบธนาคารในส่วนของผู้ส่ง: {sender_bank}")
            break 

    if not sender_bank:
        logger.warning("ไม่พบธนาคารในส่วนของผู้ส่ง กำลังทำการค้นหาทั่วไปในข้อความทั้งหมด")
        for name, kw_list in bank_keywords.items():
            bank_pattern = '|'.join([re.escape(kw) for kw in kw_list])
            if re.search(bank_pattern, text_upper):
                sender_bank = name
                logger.info(f"พบธนาคารในการค้นหาทั่วไป: {sender_bank}")
                break

    parsed_data["bank"] = sender_bank
    parsed_data["amount"] = _parse_amount(text)
    parsed_data["date"] = _find_date(text)
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

    ref_patterns = [
        r'(?:รหัสอ้างอิง|หมายเลขอ้างอิง|เลขที่อ้างอิง|เลขที่รายการ|รหัสอ้างอิง|เลขอ้างอิง|อ้างอิง|Ref|Ref\.\s*No|No\.)[\s:.]*([a-zA-Z0-9\s-]+)',
        r'\b([a-zA-Z0-9]{15,})\b'
    ]
    reference = find_first_match(text, ref_patterns)
    parsed_data["reference"] = reference.replace(" ", "") if reference else None

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
    summary.append(f"\n📝 ข้อความเต็มจากสลิป:\n```\n{raw_text}\n```")

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
            
        else:
            print(f"\nไม่สามารถประมวลผลรูปภาพ '{image_path}' ได้")