from fastapi import Header, HTTPException, Depends
import redis
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from browser_use.browser.browser import Browser
from functools import lru_cache

REDIS_URL = "redis://redis:6379/0"
SESSION_TIMEOUT = 1800  

@lru_cache()
def get_redis_client():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)

class SessionManager:
    
    def __init__(self):
        self.redis = get_redis_client()
        self.browsers = {} 
    
    async def get_session(self, session_id: Optional[str] = Header(None, alias="X-Session-ID")):
        """獲取會話，作為FastAPI依賴"""
        if session_id:
            if self.redis.exists(f"session:{session_id}"):
                self.redis.hset(f"session:{session_id}", "last_active", datetime.now().isoformat())
                self.redis.expire(f"session:{session_id}", SESSION_TIMEOUT)  
        
        return await self.create_session()
    
    async def create_session(self) -> str:
        """創建新的會話"""
        session_id = str(uuid.uuid4())
        
        self.redis.hset(
            f"session:{session_id}", 
            mapping={
                "created_at": datetime.now().isoformat(),
                "last_active": datetime.now().isoformat(),
                "current_url": "",
                "browser_id": str(uuid.uuid4())
            }
        )
        
        self.redis.expire(f"session:{session_id}", SESSION_TIMEOUT)
        
        return session_id
    
    async def get_browser(self, session_id: str, config=None) -> Browser:
        """獲取會話關聯的瀏覽器實例"""
        browser_id = self.redis.hget(f"session:{session_id}", "browser_id")
        
        if not browser_id or browser_id not in self.browsers:
            if config:
                
                config._force_keep_browser_alive = True
            
            browser = Browser(config=config)
            self.browsers[browser_id] = browser
        
        return self.browsers[browser_id]
    
    async def update_session(self, session_id: str, data: Dict[str, Any]):
        """更新會話數據"""
        self.redis.expire(f"session:{session_id}", SESSION_TIMEOUT)
        
        self.redis.hset(f"session:{session_id}", mapping=data)
    
    async def add_history(self, session_id: str, history_item: Dict[str, Any]):
        """添加歷史記錄"""
        history_key = f"history:{session_id}"
        
        history_item["timestamp"] = datetime.now().isoformat()
        self.redis.rpush(history_key, json.dumps(history_item))
        
        self.redis.expire(history_key, SESSION_TIMEOUT)
    
    async def get_session_data(self, session_id: str) -> Dict[str, Any]:
        """獲取會話數據"""
        data = self.redis.hgetall(f"session:{session_id}")
        
        if not data:
            raise HTTPException(status_code=404, detail="Session not found")
            
        return data
    
    async def get_history(self, session_id: str, limit: int = -1) -> list:
        """獲取會話歷史記錄"""
        history_key = f"history:{session_id}"
        
        if limit > 0:
            raw_items = self.redis.lrange(history_key, -limit, -1)
        else:
            raw_items = self.redis.lrange(history_key, 0, -1)
            
        return [json.loads(item) for item in raw_items]
    
    async def clear_inactive_sessions(self):
        """清理不活躍的會話和釋放資源"""
        for key in self.redis.keys("session:*"):
            session_id = key.split(":", 1)[1]
            last_active = self.redis.hget(key, "last_active")
            
            if not last_active:
                continue
                
            last_active_time = datetime.fromisoformat(last_active)
            if datetime.now() - last_active_time > timedelta(seconds=SESSION_TIMEOUT):
                browser_id = self.redis.hget(key, "browser_id")
                if browser_id in self.browsers:
                    browser = self.browsers.pop(browser_id)
                    await browser.close()
                
                self.redis.delete(key)
                self.redis.delete(f"history:{session_id}")


session_manager = SessionManager()

def get_session_manager():
    return session_manager