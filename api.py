from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, SecretStr
from langchain_google_genai import ChatGoogleGenerativeAI
from browser_use import Agent
from browser_use.browser.browser import BrowserConfig
from browser_use.browser.context import BrowserContextConfig
import os
from dotenv import load_dotenv
import asyncio
from typing import Optional, Dict, Any
from fastapi.middleware.cors import CORSMiddleware
import logging
from langchain.schema import HumanMessage
from session_manager import session_manager, get_session_manager
import base64

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

# LLM設置
llm = ChatGoogleGenerativeAI(
    model='gemini-2.0-flash-exp',
    api_key=SecretStr(os.getenv('GEMINI_API_KEY'))
)

class TaskRequest(BaseModel):
    task: str
    include_screenshot: bool = True
    timeout: Optional[int] = 30
    sensitive_data: Optional[Dict[str, str]] = None
    new_session: bool = False  # 是否創建新會話

class TaskResponse(BaseModel):
    status: str
    message: str
    screenshot: Optional[str] = None
    session_id: str
    current_url: Optional[str] = None

# 定期清理過期會話
@app.on_event("startup")
async def startup_event():
    async def cleanup_task():
        while True:
            await session_manager.clear_inactive_sessions()
            await asyncio.sleep(300)  # 每5分鐘檢查一次
    
    asyncio.create_task(cleanup_task())

async def process_user_task(task: str, current_url: str = None) -> str:
    """處理用戶任務生成指令"""
    try:
        context = f"The current browser page is at URL: {current_url}. " if current_url else ""
        
        prompt = f"""
        You are a browser automation assistant. {context}Convert the following user request into clear, 
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
        return task

@app.post("/execute-task", response_model=TaskResponse)
async def execute_task(
    request: TaskRequest, 
    background_tasks: BackgroundTasks,
    session_manager = Depends(get_session_manager),
    session_id: str = Depends(session_manager.get_session)
):
    try:

        if request.new_session:
            session_id = await session_manager.create_session()
        
        logger.info(f"Session ID: {session_id}")
        logger.info(f"Received task: {request.task}")
        
        session_data = await session_manager.get_session_data(session_id)
        current_url = session_data.get("current_url")
        
        detailed_task = await process_user_task(request.task, current_url)
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
                highlight_elements=True,
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
        
    
        agent = Agent(
            task=detailed_task,
            llm=llm,
            browser=browser,
            sensitive_data=request.sensitive_data
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
            
            if request.include_screenshot and hasattr(last_history, 'state') and last_history.state.screenshot:
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
            current_url=new_url
        )
    except Exception as e:
        logger.error(f"Error executing task: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error executing task: {str(e)}"
        )

@app.get("/session/info")
async def get_session_info(
    session_manager = Depends(get_session_manager),
    session_id: str = Depends(session_manager.get_session)
):
    """get session info"""
    try:
        session_data = await session_manager.get_session_data(session_id)
        history = await session_manager.get_history(session_id)
        
        return {
            "session_id": session_id,
            "created_at": session_data.get("created_at"),
            "current_url": session_data.get("current_url"),
            "history_count": len(history)
        }
    except Exception as e:
        logger.error(f"Error getting session info: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/session/history")
async def get_session_history(
    limit: int = 10,
    session_manager = Depends(get_session_manager),
    session_id: str = Depends(session_manager.get_session)
):
    """get session history"""
    try:
        history = await session_manager.get_history(session_id, limit)
        return {
            "session_id": session_id,
            "history": history
        }
    except Exception as e:
        logger.error(f"Error getting session history: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/session/new")
async def create_new_session(
    session_manager = Depends(get_session_manager)
):
    """create new session"""
    try:
        session_id = await session_manager.create_session()
        return {
            "session_id": session_id,
            "message": "New session created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating new session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/session/{session_id}/clean-screenshot")
async def get_clean_screenshot(
    session_id: str,
    full_page: bool = True,
    session_manager = Depends(get_session_manager)
):
    """get clean screenshot"""
    try:
        
        session_data = await session_manager.get_session_data(session_id)
        browser_id = session_data.get("browser_id")
        
        if not browser_id or browser_id not in session_manager.browsers:
            raise HTTPException(status_code=404, detail="No active browser for this session")
        
        browser = session_manager.browsers[browser_id]
        
        if not hasattr(browser, 'playwright_browser') or not browser.playwright_browser:
            logger.info("Browser is not initialized, initializing now")
            await browser.get_playwright_browser()
        
        if not hasattr(browser, 'context') or not browser.context:
            logger.info("No existing browser context, creating new one")
            browser.context = await browser.new_context()
        
        try:
            existing_pages = browser.playwright_browser.contexts[0].pages if browser.playwright_browser.contexts else []
            
            if not existing_pages:
                logger.info("No existing pages found, creating a new page")
                page = await browser.playwright_browser.contexts[0].new_page()
                
                current_url = session_data.get("current_url")
                if current_url:
                    try:
                        logger.info(f"Navigating to {current_url}")
                        await page.goto(current_url, wait_until="networkidle", timeout=20000)
                        await page.wait_for_load_state("domcontentloaded")
                        logger.info(f"Page loaded for screenshot")
                    except Exception as e:
                        logger.error(f"Failed to navigate to {current_url}: {str(e)}")
                        await page.goto("about:blank")
                else:
                    await page.goto("about:blank")
            else:
                logger.info(f"Using existing page for screenshot")
                page = existing_pages[0]
                
                try:
                    await page.reload(wait_until="networkidle", timeout=20000)
                    await page.wait_for_load_state("domcontentloaded")
                except Exception as e:
                    logger.warning(f"Failed to reload page: {str(e)}")
                
                logger.info(f"Using existing page at URL: {page.url}")
            
            await page.bring_to_front()
            
            if full_page:
                try:
                    await page.evaluate("""
                        window.scrollTo(0, document.body.scrollHeight);
                        setTimeout(() => { window.scrollTo(0, 0); }, 100);
                    """)
                    await asyncio.sleep(0.5)
                except Exception as scroll_err:
                    logger.debug(f"Error during page scroll: {scroll_err}")
            
            await asyncio.sleep(0.5)
            
            screenshot_bytes = await page.screenshot(full_page=full_page)
            
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            
            
            return {"screenshot": screenshot_base64}
                
        except Exception as e:
            logger.error(f"Failed to use browser page: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to use browser page: {str(e)}")
    except Exception as e:
        logger.error(f"Error capturing clean screenshot: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)