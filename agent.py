import os
import asyncio
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from langchain_groq import ChatGroq
from langchain.agents import create_agent
from langchain_community.tools import DuckDuckGoSearchRun

load_dotenv()
logging.basicConfig(level=logging.INFO)

# جلب المفاتيح
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# إعداد الذكاء (Groq)
llm = ChatGroq(
    temperature=0.3, 
    groq_api_key=GROQ_API_KEY, 
    model_name="llama-3.3-70b-versatile"
)

# الأدوات (Tools)
search_tool = DuckDuckGoSearchRun()
tools = [search_tool]

# إنشاء الوكيل بالطريقة الجديدة (LangChain 1.0)
agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt="أنت وكيل ذكاء اصطناعي خارق وشخصي. تجيب على الأسئلة، تبحث في الإنترنت عند الحاجة، وتشرح بذكاء. اكتب الأكواد بين ```."
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("أهلاً بك! أنا وكيلك الذكي الخارق. اسألني أي شي، وأنا أفكر وأبحث لك عن الإجابة. 🤖🔍")

@dp.message(F.text)
async def handle_message(message: types.Message):
    user_text = message.text
    await message.answer("🧠 جاري التفكير والبحث...")
    
    try:
        # استدعاء الوكيل بالطريقة الجديدة
        response = await agent.ainvoke({
            "messages": [{"role": "user", "content": user_text}]
        })
        
        # استخراج الرد النصي
        reply = response["messages"][-1].content
        await message.answer(reply)
        
    except Exception as e:
        logging.error(f"Error: {e}")
        await message.answer("⚠️ حدث خطأ، جرب مرة ثانية.")

async def main():
    print("🚀 الوكيل شغال...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
