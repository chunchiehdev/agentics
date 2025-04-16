from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, SecretStr
from langchain_google_genai import ChatGoogleGenerativeAI
from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig
import os
from dotenv import load_dotenv
import asyncio
import base64
from typing import Optional, List, Dict, Any
from fastapi.middleware.cors import CORSMiddleware
import logging

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

@app.post("/execute-task", response_model=TaskResponse)
async def execute_task(request: TaskRequest):
    try:
        logger.info(f"Received task: {request.task}")
        
        browser_config = BrowserConfig(
            headless=True,
            disable_security=True
        )
        
        browser = Browser(config=browser_config)
        
        agent = Agent(
            task=request.task,
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
                last_result = last_history.result[-1]
                if hasattr(last_result, 'extracted_content') and last_result.extracted_content:
                    result_message = last_result.extracted_content
        
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