from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, SecretStr
from langchain_google_genai import ChatGoogleGenerativeAI
from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContextConfig
import os
from dotenv import load_dotenv
import asyncio
import base64
from typing import Optional, List, Dict, Any
from fastapi.middleware.cors import CORSMiddleware
import logging
from langchain.schema import HumanMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Browser Automation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"],  
)

llm = ChatGoogleGenerativeAI(
    model='gemini-2.0-flash-exp',
    api_key=SecretStr(os.getenv('GEMINI_API_KEY'))
)

class TaskRequest(BaseModel):
    task: str
    include_screenshot: bool = True
    timeout: Optional[int] = 30
    sensitive_data: Optional[Dict[str, str]] = None

class TaskResponse(BaseModel):
    status: str
    message: str
    screenshot: Optional[str] = None

async def process_user_task(task: str) -> str:
    """
    Pre-process the user's natural language task to generate more specific browser automation instructions.
    This helps convert vague user requests into detailed steps for the automation agent.
    """
    try:
        prompt = f"""
        You are a browser automation assistant. Convert the following user request into clear, 
        step-by-step browser instructions that an automation agent can follow.
        
        For example, if the user says "check the weather in New York", you should generate:
        "1. Go to weather.com
        2. Search for New York
        3. Find and extract the current temperature and conditions"
        
        Be precise and include all necessary details for automation.
        If the user request involves login, make sure to specify to use placeholder values that 
        will be replaced by sensitive data.
        
        User Request: {task}
        
        Step-by-step instructions:
        """
        
        messages = [HumanMessage(content=prompt)]
        response = await llm.ainvoke(messages)
        
        logger.info("Processed user task into detailed instructions")
        return response.content
    except Exception as e:
        logger.error(f"Error in task processing: {str(e)}", exc_info=True)
        # If there's an error, return the original task
        return task

@app.post("/execute-task", response_model=TaskResponse)
async def execute_task(request: TaskRequest):
    try:
        logger.info(f"Received task: {request.task}")
        
        # Process user task to get detailed instructions
        detailed_task = await process_user_task(request.task)
        logger.info(f"Processed task: {detailed_task}")
        
        # Create an optimized browser context config
        browser_context_config = BrowserContextConfig(
            # Page load settings - increase for slower or complex pages
            minimum_wait_page_load_time=1.0,
            wait_for_network_idle_page_load_time=3.0,
            maximum_wait_page_load_time=8.0,
            
            # Browser display and identity settings
            browser_window_size={'width': 1920, 'height': 1080},  # Full HD resolution common for real users
            locale='en-US',  # Set a common locale
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            
            # UI settings
            highlight_elements=True,  # Visual indicator of interactive elements
            viewport_expansion=800,  # Include more content for better context
            
            # Wait between actions to simulate human behavior
            wait_between_actions=1.0,
        )
        
        # Configure browser with anti-detection measures
        browser_config = BrowserConfig(
            headless=True,
            disable_security=True,
            new_context_config=browser_context_config,
            # Anti-detection arguments
            extra_chromium_args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins",
                "--disable-site-isolation-trials",
                "--disable-web-security",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
            ]
        )
        
        browser = Browser(config=browser_config)
        
        agent = Agent(
            task=detailed_task,
            llm=llm,
            browser=browser,
            sensitive_data=request.sensitive_data
        )
        
        logger.info("Starting task execution")
        history = await agent.run()
        logger.info("Task execution completed successfully")
        
        screenshot = None
        result_message = "Task execution completed"
        
        if history.history and len(history.history) > 0:
            last_history = history.history[-1]
            
            if request.include_screenshot and hasattr(last_history, 'state') and last_history.state.screenshot:
                screenshot = last_history.state.screenshot
            
            if hasattr(last_history, 'result') and last_history.result and len(last_history.result) > 0:
                last_result = history.history[-1].result[-1]
                if hasattr(last_result, 'extracted_content') and last_result.extracted_content:
                    result_message = last_result.extracted_content
            
            # Check if CAPTCHA was encountered
            for hist in history.history:
                if hasattr(hist, 'eval') and hist.eval:
                    eval_text = getattr(hist.eval, 'text', '')
                    if eval_text and ('captcha' in eval_text.lower() or 'recaptcha' in eval_text.lower()):
                        result_message = "Note: A CAPTCHA was detected during the task. " + result_message
                        break
        
        return TaskResponse(
            status="success",
            message=result_message,
            screenshot=screenshot
        )
    except Exception as e:
        logger.error(f"Error executing task: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error executing task: {str(e)}"
        )

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 