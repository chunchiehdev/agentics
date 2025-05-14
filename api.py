from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from pydantic import BaseModel, SecretStr
from langchain_google_genai import ChatGoogleGenerativeAI
from browser_use import Agent
from browser_use.browser.browser import BrowserConfig
from browser_use.browser.context import BrowserContextConfig
import os
from dotenv import load_dotenv
import asyncio
from typing import Optional, Dict, Any, List
from fastapi.middleware.cors import CORSMiddleware
import logging
from langchain.schema import HumanMessage
from session_manager import session_manager, get_session_manager
import base64
import httpx
import json
from datetime import datetime
from fastapi.responses import StreamingResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

RAGFLOW_API = os.getenv(RAGFLOW_API)
RAGFLOW_API_KEY = os.getenv('RAGFLOW_API_KEY')
RAGFLOW_DATASET_ID = os.getenv('RAGFLOW_DATASET_ID')
RAGFLOW_CHAT_ID = os.getenv('RAGFLOW_CHAT_ID')

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

class SensitiveField(BaseModel):
    key: str
    value: str

class TaskRequest(BaseModel):
    task: str
    include_screenshot: bool = True
    timeout: Optional[int] = 30
    sensitive_data: Optional[List[SensitiveField]] = None 
    new_session: bool = False
    ragflow_session_id: Optional[str] = None

class TaskResponse(BaseModel):
    status: str
    message: str
    screenshot: Optional[str] = None
    session_id: str
    current_url: Optional[str] = None
    ragflow_session_id: Optional[str] = None

class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None
    stream: str = "true"  

async def process_user_task(task: str, current_url: str = None) -> str:  
    """Process task using default LLM."""
    try:  
        context = f"The current browser page is at URL: {current_url}. " if current_url else ""
        prompt = f"""
        You are a browser automation assistant. {context}
        Convert the following user request into clear,
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
        logger.info("Processed user task using default LLM")
        return response.content

    except Exception as e:  
        logger.error(f"Error in process_user_task: {str(e)}", exc_info=True)  
        raise HTTPException(
            status_code=500,
            detail=f"Error processing task: {str(e)}"
        )

async def call_ragflow_api(question: str, session_id: Optional[str] = None, stream: str = "false"):
    """Shared function to call RAGFlow API"""
    async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
        request_url = f"{RAGFLOW_API}/api/v1/chats/{RAGFLOW_CHAT_ID}/completions"
        request_headers = {
            "Authorization": f"Bearer {RAGFLOW_API_KEY}",
            "Content-Type": "application/json"
        }
        request_body = {
            "question": question,
            "stream": stream
        }
        
        if session_id:
            request_body["session_id"] = session_id

        logger.info(f"[RAGFlow] Sending request to: {request_url}")
        logger.info(f"[RAGFlow] Request body: {request_body}")

        response = await client.post(
            request_url,
            headers=request_headers,
            json=request_body
        )
        logger.info(f"[RAGFlow] Response Status: {response.status_code}")
        logger.info(f"[RAGFlow] Raw Response: {response.text}")
        response.raise_for_status()

        try:
            lines = response.text.strip().split('\n')
            logger.info(f"[RAGFlow] Response lines: {lines}")
            last_valid_data = None
            for line in lines:
                if line.startswith('data:'):
                    try:
                        json_str = line[5:].strip()
                        logger.info(f"[RAGFlow] Processing line: {json_str}")
                        data = json.loads(json_str)
                        if data.get('data') and data.get('data') is not True:
                            last_valid_data = data
                            logger.info(f"[RAGFlow] Found valid data: {data}")
                    except json.JSONDecodeError as e:
                        logger.error(f"[RAGFlow] JSON decode error: {str(e)}")
                        continue
            
            if not last_valid_data:
                logger.error("[RAGFlow] No valid data found in response")
                raise HTTPException(
                    status_code=500,
                    detail="No valid data found in response"
                )
            
            return last_valid_data

        except json.JSONDecodeError as e:
            logger.error(f"[RAGFlow] Failed to parse response: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Invalid response from RAGFlow API: {str(e)}"
            )

@app.post("/api/execute-task", response_model=TaskResponse)
async def execute_task(
    request: TaskRequest, 
    background_tasks: BackgroundTasks,
    session_manager = Depends(get_session_manager),
    session_id: str = Depends(session_manager.get_session)
):
    try:
        if request.new_session:
            session_id = await session_manager.create_session()
        
        logger.info(f"Redis Session ID: {session_id}")
        logger.info(f"RAGFlow Session ID: {request.ragflow_session_id}")
        logger.info(f"Received task: {request.task}")
        
        if not request.ragflow_session_id:
            ragflow_response_01 = await call_ragflow_api(
                question=request.task,
                session_id=None,
                stream="false"
            )
            
            if not ragflow_response_01.get('data', {}).get('session_id'):
                raise HTTPException(
                    status_code=500,
                    detail="Failed to get RAGFlow session ID"
                )
            
            request.ragflow_session_id = ragflow_response_01['data']['session_id']
            logger.info(f"Got new RAGFlow session ID: {request.ragflow_session_id}")
            
            ragflow_response = await call_ragflow_api(
                question=request.task,
                session_id=request.ragflow_session_id,
                stream="false"
            )
        else:
            ragflow_response = await call_ragflow_api(
                question=request.task,
                session_id=request.ragflow_session_id,
                stream="false"
            )
        
        if not ragflow_response.get('data', {}).get('answer'):
            raise HTTPException(
                status_code=500,
                detail="No valid response from RAGFlow"
            )
        
        ragflow_answer = ragflow_response['data']['answer']
        logger.info(f"RAGFlow response: {ragflow_answer}")
        
        session_data = await session_manager.get_session_data(session_id)
        current_url = session_data.get("current_url")
        
        detailed_task = await process_user_task(
            f"Original task: {request.task}\nRAGFlow understanding: {ragflow_answer}",
            current_url
        )
        logger.info(f"Processed task: {detailed_task}")
        
        browser_config = BrowserConfig(
            headless=True,
            disable_security=True,
            new_context_config=BrowserContextConfig(
                minimum_wait_page_load_time=1.0,
                wait_for_network_idle_page_load_time=3.0,
                maximum_wait_page_load_time=8.0,
                browser_window_size={'width': 1920, 'height': 1080},
                locale='en-US',
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                highlight_elements=False,
                viewport_expansion=800,
                wait_between_actions=1.0,
            ),
            extra_chromium_args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins",
                "--disable-site-isolation-trials",
                "--disable-web-security",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
            ],
            _force_keep_browser_alive=True  
        )
        
        browser = await session_manager.get_browser(session_id, browser_config)
        sensitive_data_dict = {}
        if request.sensitive_data:
            sensitive_data_dict = {field.key: field.value for field in request.sensitive_data}
        
        agent = Agent(
            task=detailed_task,
            llm=llm,
            browser=browser,
            sensitive_data=sensitive_data_dict
        )
        
        logger.info("Starting task execution")
        history = await agent.run()
        logger.info("Task execution completed successfully")
        
        if hasattr(browser, 'context') and browser.context and browser.context.pages:
            logger.info(f"Keeping {len(browser.context.pages)} browser pages active after task")
        
        screenshot = None
        result_message = "Task execution completed"
        new_url = None
        
        if history.history and len(history.history) > 0:
            last_history = history.history[-1]
            
            if hasattr(last_history, 'state') and hasattr(last_history.state, 'url'):
                new_url = last_history.state.url
                await session_manager.update_session(session_id, {"current_url": new_url})
            
            if request.include_screenshot:
                try:
                    clean_screenshot = await get_clean_screenshot(session_id, True, session_manager)
                    screenshot = clean_screenshot["screenshot"]
                except Exception as e:
                    logger.error(f"Failed to get clean screenshot: {str(e)}")
                    if hasattr(last_history, 'state') and last_history.state.screenshot:
                        screenshot = last_history.state.screenshot
            
            if hasattr(last_history, 'result') and last_history.result and len(last_history.result) > 0:
                last_result = history.history[-1].result[-1]
                if hasattr(last_result, 'extracted_content') and last_result.extracted_content:
                    result_message = last_result.extracted_content
            
            for hist in history.history:
                if hasattr(hist, 'eval') and hist.eval:
                    eval_text = getattr(hist.eval, 'text', '')
                    if eval_text and ('captcha' in eval_text.lower() or 'recaptcha' in eval_text.lower()):
                        result_message = "Note: A CAPTCHA was detected during the task. " + result_message
                        break
        
        background_tasks.add_task(
            session_manager.add_history,
            session_id,
            {
                "task": request.task,
                "ragflow_response": ragflow_answer,
                "detailed_task": detailed_task,
                "result": result_message,
                "url": new_url
            }
        )
        
        return TaskResponse(
            status="success",
            message=result_message,
            screenshot=screenshot,
            session_id=session_id,
            current_url=new_url,
            ragflow_session_id=request.ragflow_session_id
        )
    except Exception as e:
        logger.error(f"Error executing task: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error executing task: {str(e)}"
        )

async def get_clean_screenshot(
    session_id: str,
    full_page: bool = True,
    session_manager = Depends(get_session_manager)
):
    """Get a clean screenshot without highlights"""
    try:
        session_data = await session_manager.get_session_data(session_id)
        browser_id = session_data.get("browser_id")
        
        if not browser_id or browser_id not in session_manager.browsers:
            raise HTTPException(status_code=404, detail="No active browser for this session")
        
        browser = session_manager.browsers[browser_id]
        
        if not hasattr(browser, 'playwright_browser') or not browser.playwright_browser:
            await browser.get_playwright_browser()
        
        page = browser.playwright_browser.contexts[0].pages[0] if browser.playwright_browser.contexts else None
        if not page:
            raise HTTPException(status_code=404, detail="No active page found")
        
        await browser.context.remove_highlights()


        screenshot_bytes = await page.screenshot(full_page=full_page)
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        
        return {"screenshot": screenshot_base64}
                
    except Exception as e:
        logger.error(f"Error capturing clean screenshot: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/session/{session_id}/clean-screenshot")
async def get_clean_screenshot_endpoint(
    session_id: str,
    full_page: bool = True,
    session_manager = Depends(get_session_manager)
):
    """Endpoint to get a clean screenshot of the current page"""
    return await get_clean_screenshot(session_id, full_page, session_manager)

@app.post("/api/v1/ragflow/completions")
async def ragflow_completions(request: ChatRequest):
    try:
        logger.info(f"[RAGFlow] Request details:")
        logger.info(f"[RAGFlow] - Session ID: {request.session_id}")
        logger.info(f"[RAGFlow] - Question: {request.question}")
        logger.info(f"[RAGFlow] - Stream: {request.stream}")

        response = await call_ragflow_api(
            question=request.question,
            session_id=request.session_id,
            stream=request.stream
        )
        return response

    except Exception as e:
        logger.error(f"[RAGFlow] Error in completions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)