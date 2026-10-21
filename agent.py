import os
import logging
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from langchain_groq import ChatGroq
from langchain.agents import create_agent
from langchain_community.tools import DuckDuckGoSearchRun
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# رابط خدمتك في Render (سيتم إضافته كمتغير بيئة)
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", "https://your-app.onrender.com")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

llm = ChatGroq(temperature=0.3, groq_api_key=GROQ_API_KEY, model_name="llama-3.3-70b-versatile")
search_tool = DuckDuckGoSearchRun()
tools = [search_tool]

agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt="أنت وكيل ذكاء اصطناعي خارق وشخصي. تجيب على الأسئلة، تبحث في الإنترنت عند الحاجة، وتشرح بذكاء. اكتب الأكواد بين ```."
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("أهلاً بك! أنا وكيلك الذكي الخارق. اسألني أي شي. 🤖🔍")

@dp.message(F.text)
async def handle_message(message: types.Message):
    await message.answer("🧠 جاري التفكير والبحث...")
    try:
        response = await agent.ainvoke({"messages": [{"role": "user", "content": message.text}]})
        await message.answer(response["messages"][-1].content)
    except Exception as e:
        logging.error(f"Error: {e}")
        await message.answer("⚠️ حدث خطأ، جرب مرة ثانية.")

# دالة للتحقق من صحة الخدمة (Health Check) لإرضاء Render
async def health_check(request):
    return web.Response(text="OK")

async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook set to {WEBHOOK_URL}")

def main():
    app = web.Application()
    
    # إعداد Webhook
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    
    # إضافة مسار Health Check
    app.router.add_get("/", health_check)
    
    # تشغيل السيرفر
    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=port, on_startup=[lambda _: asyncio.create_task(on_startup(bot))])

if __name__ == "__main__":
    main()
