import os
import logging
import asyncio
import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from langchain_groq import ChatGroq
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", "https://your-app.onrender.com")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# --- قاعدة البيانات ---
DB_PATH = "agent.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def save_message(user_id, role, content):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )
        await db.commit()

async def get_history(user_id, limit=6):  # 6 رسائل (3 أسئلة + 3 أجوبة)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

# --- إعداد الذكاء الاصطناعي ---
llm = ChatGroq(
    temperature=0.5, 
    groq_api_key=GROQ_API_KEY, 
    model_name="openai/gpt-oss-20b"
)

# تعليمات الشخصية (System Prompt) - منظمة وذكية
system_prompt = """أنت وكيل ذكاء اصطناعي شخصي، اسمك "سوبر". أنت ودود، تستخدم الإيموجي (😊، 🤔، 📝).

قواعد صارمة:
1. لا تسأل "هل تريد ملخصاً أم شرحاً كاملاً" إلا إذا كان الطلب غامضاً جداً (مثل: "اشرح لي هذا").
2. إذا اختار المستخدم (ملخص) أو (شرح كامل)، قدم المطلوب مباشرةً، ولا تكرر السؤال نهائياً.
3. إذا كان الطلب واضحاً (مثل: "ابغا اسوي بوت")، ابدأ بالخطوات فوراً دون سؤال.
4. لا تصحح أخطاء المستخدم الإملائية، بل افهم قصده.
5. إذا كان الرد طويلاً، قدمه على شكل خطوات قصيرة (1، 2، 3)، وانتظر موافقة المستخدم.
6. لا تستخدم الجداول (|) أو أي رموز Markdown مثل ** أو ##. استخدم النقاط العادية (1، 2، 3) أو (-) فقط.
7. لا تستخدم وسوم HTML مثل <br> أو <b>.
8. استخدم لغة عربية سليمة.
9. تذكر سياق المحادثة السابقة، ولا تنسَ ما قاله المستخدم."""

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("أهلاً بك! أنا وكيلك الذكي الشخصي. اسألني أي شي، وسأكون معك خطوة بخطوة! 🤖✨")

@dp.message(F.text)
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    user_text = message.text

    await message.answer("🧠 جاري التفكير...")

    try:
        # جلب آخر 6 رسائل (للسياق)
        history = await get_history(user_id)
        
        # تجهيز الرسائل
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        
        response = await llm.ainvoke(messages)
        reply = response.content
        
        # حفظ في قاعدة البيانات
        await save_message(user_id, "user", user_text)
        await save_message(user_id, "assistant", reply)
        
        await message.answer(reply)
    except Exception as e:
        logging.error(f"Error: {e}")
        await message.answer("⚠️ عذراً، حدث خطأ بسيط. جرب مرة ثانية! 💪")

# --- إعداد السيرفر والويب هوك ---
async def on_startup(app):
    await init_db()
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"✅ Webhook set to {WEBHOOK_URL}")

async def health_check(request):
    return web.Response(text="OK")

async def main():
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    app.router.add_get("/", health_check)
    app.on_startup.append(on_startup)
    
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    print(f"🚀 الوكيل شغال على المنفذ {port}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
