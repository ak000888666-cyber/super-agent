import os
import asyncio
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from langchain_groq import ChatGroq
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.prompts import ChatPromptTemplate

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

# تعليمات الوكيل (شخصيته)
prompt = ChatPromptTemplate.from_messages([
    ("system", "أنت وكيل ذكاء اصطناعي خارق وشخصي. تجيب على الأسئلة، تبحث في الإنترنت عند الحاجة، وتشرح بذكاء. اكتب الأكواد بين ```."),
    ("placeholder", "{chat_history}"),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

# إنشاء الوكيل
agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

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
        # الوكيل يحاول يحل السؤال (ويستخدم البحث لو احتاج)
        response = await agent_executor.ainvoke({"input": user_text})
        await message.answer(response["output"])
    except Exception as e:
        logging.error(f"Error: {e}")
        await message.answer("⚠️ حدث خطأ، جرب مرة ثانية.")

async def main():
    print("🚀 الوكيل شغال...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
