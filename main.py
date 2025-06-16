import uvicorn
from fastapi import FastAPI
from app.router import webhook_router
import os

# สร้าง FastAPI instance
app = FastAPI(
    title="AI Chat Assistant QR - LINE Bot",
    description="LINE Bot for reading payment slips with OCR",
    version="1.0.0"
)

# รวม router จาก app/router.py
app.include_router(webhook_router)

@app.get("/")
async def root():
    """Health check endpoint - ตรวจสอบว่าระบบทำงานปกติ"""
    return {
        "message": "AI Chat Assistant QR - LINE Bot is running", 
        "status": "ok",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    """Additional health check endpoint"""
    return {"status": "healthy", "service": "line-bot"}

# รันเซิร์ฟเวอร์
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    # เปลี่ยนจาก "0.0.0.0" เป็น "127.0.0.1" สำหรับการทดสอบ local
    # หรือใช้ "localhost" 
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=True)
