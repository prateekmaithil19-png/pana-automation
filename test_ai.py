"""
Quick local test — simulates customer messages and shows what the AI replies.
Run: python test_ai.py
"""
import asyncio
import os

# Load .env
from dotenv import load_dotenv
load_dotenv()

from ai.engine import generate_reply
from ai.classifier import is_pricing_request, detect_language

TEST_MESSAGES = [
    "สวัสดีค่ะ อยากสอบถามเรื่องถ่ายภาพสินค้าค่ะ",
    "ราคาเท่าไหร่คะ",
    "มีแพ็กเกจอะไรบ้าง",
    "ถ่ายเสื้อผ้าค่ะ มีประมาณ 10 ชุด อยากได้นางแบบด้วย",
    "ได้ไฟล์กี่วันคะ",
    "Hi, I want to book a product shoot, how much does it cost?",
    "มีเครื่องประดับด้วย คิดราคายังไงคะ",
    "อยากได้สไตล์ minimal สีนู้ดค่ะ",
]

async def test():
    print("=" * 60)
    print("🤖 Pana Studio AI — Test Mode")
    print("=" * 60)

    history = []

    for msg in TEST_MESSAGES:
        lang = detect_language(msg)
        pricing = is_pricing_request(msg)

        print(f"\n👤 Customer [{lang.upper()}{'  💰 PRICING' if pricing else ''}]:")
        print(f"   {msg}")

        reply = await generate_reply(msg, history)

        print(f"\n🤖 AI Reply:")
        print(f"   {reply}")
        print("-" * 60)

        # Build up conversation history
        history.append({"role": "customer", "content": msg})
        history.append({"role": "assistant", "content": reply})

        # Keep history short
        if len(history) > 6:
            history = history[-6:]

if __name__ == "__main__":
    asyncio.run(test())
