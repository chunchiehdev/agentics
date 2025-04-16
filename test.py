from langchain_google_genai import ChatGoogleGenerativeAI
from browser_use import Agent
from pydantic import SecretStr
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

# Initialize the model
llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(os.getenv('GEMINI_API_KEY')))

# Create agent with the model
agent = Agent(
    task="""
    go to this link 'https://portal.ncu.edu.tw/login', and find the account field and password field. Type '123' in the account field, 
    and type '456' in the password field. If you see a checkbox that says 'I'm not a robot', 
    find that checkbox and click it. Wait for 3 seconds after clicking the checkbox, then click the login button..
    """,
    llm=llm
)


async def main():
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())