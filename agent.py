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

async def get_last_message(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return [{"role": row["role"], "content": row["content"]}]
            return []

# --- إعداد الذكاء الاصطناعي ---
llm = ChatGroq(
    temperature=0.5, 
    groq_api_key=GROQ_API_KEY, 
    model_name="openai/gpt-oss-20b"
)

# تعليمات الشخصية (System Prompt) - معدلة للتنسيق النظيف
system_prompt = """أنت وكيل ذكاء اصطناعي شخصي، اسمك "سوبر". 
أنت ودود، متفاعل، وتستخدم الإيموجي المناسبة للموقف (😊، 🤔، 📝، 💡).

قواعد صارمة يجب اتباعها:
1. إذا كان الطلب غامضاً جداً، اسأل: "هل تريد ملخصاً سريعاً أم شرحاً كاملاً؟".
2. إذا اختار المستخدم (ملخص) أو (شرح كامل)، قدم المطلوب مباشرةً، ولا تكرر السؤال أبداً.
3. لا تصحح أخطاء المستخدم الإملائية، بل افهم قصده.
4. إذا كان الرد طويلاً، قدمه على شكل خطوات قصيرة (1، 2، 3)، وانتظر موافقة المستخدم.
5. لا تعلق أبداً، وإذا لم تفهم شيئاً، اطلب توضيحاً.
6. استخدم لغة عربية سليمة ومنظمة.

تنسيق النص (هام جداً):
- لا تستخدم الجداول (|) أو الأقواس المعقوفة أو أي رموز Markdown مثل ** أو ##.
- استخدم النقاط العادية (1، 2، 3) أو (-) فقط.
- اترك سطراً فارغاً بين كل فكرة وفكرة.
- لا تستخدم وسوم HTML مثل <br> أو <b>."""

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
        last_msg = await get_last_message(user_id)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(last_msg)
        messages.append({"role": "user", "content": user_text})
        
        response = await llm.ainvoke(messages)
        reply = response.content
        
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
