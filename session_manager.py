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
            # 檢查會話是否存在
            if self.redis.exists(f"session:{session_id}"):
                # 更新會話活動時間
                self.redis.hset(f"session:{session_id}", "last_active", datetime.now().isoformat())
                self.redis.expire(f"session:{session_id}", SESSION_TIMEOUT)  # 刷新過期時間
                return session_id
        
        # 如果session_id為空或者不存在，創建新會話
        return await self.create_session()
    
    async def create_session(self) -> str:
        """創建新的會話"""
        session_id = str(uuid.uuid4())
        
        # 設置會話數據
        self.redis.hset(
            f"session:{session_id}", 
            mapping={
                "created_at": datetime.now().isoformat(),
                "last_active": datetime.now().isoformat(),
                "current_url": "",
                "browser_id": str(uuid.uuid4())
            }
        )
        
        # 設置過期時間
        self.redis.expire(f"session:{session_id}", SESSION_TIMEOUT)
        
        return session_id
    
    async def get_browser(self, session_id: str, config=None) -> Browser:
        """獲取會話關聯的瀏覽器實例"""
        browser_id = self.redis.hget(f"session:{session_id}", "browser_id")
        
        if not browser_id or browser_id not in self.browsers:
            # 創建新瀏覽器實例
            if config:
                # Make sure browser stays alive after operations
                config._force_keep_browser_alive = True
            
            browser = Browser(config=config)
            self.browsers[browser_id] = browser
        
        return self.browsers[browser_id]
    
    async def update_session(self, session_id: str, data: Dict[str, Any]):
        """更新會話數據"""
        # 刷新過期時間
        self.redis.expire(f"session:{session_id}", SESSION_TIMEOUT)
        
        # 更新數據
        self.redis.hset(f"session:{session_id}", mapping=data)
    
    async def add_history(self, session_id: str, history_item: Dict[str, Any]):
        """添加歷史記錄"""
        history_key = f"history:{session_id}"
        
        # 添加帶時間戳的記錄
        history_item["timestamp"] = datetime.now().isoformat()
        self.redis.rpush(history_key, json.dumps(history_item))
        
        # 設置過期時間與會話相同
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
        
        # 獲取最新的N條記錄
        if limit > 0:
            raw_items = self.redis.lrange(history_key, -limit, -1)
        else:
            raw_items = self.redis.lrange(history_key, 0, -1)
            
        return [json.loads(item) for item in raw_items]
    
    async def clear_inactive_sessions(self):
        """清理不活躍的會話和釋放資源"""
        # 尋找所有會話
        for key in self.redis.keys("session:*"):
            session_id = key.split(":", 1)[1]
            last_active = self.redis.hget(key, "last_active")
            
            if not last_active:
                continue
                
            # 檢查最後活動時間
            last_active_time = datetime.fromisoformat(last_active)
            if datetime.now() - last_active_time > timedelta(seconds=SESSION_TIMEOUT):
                # 關閉瀏覽器
                browser_id = self.redis.hget(key, "browser_id")
                if browser_id in self.browsers:
                    browser = self.browsers.pop(browser_id)
                    await browser.close()
                
                # 刪除會話和歷史
                self.redis.delete(key)
                self.redis.delete(f"history:{session_id}")

# 創建全局單例
session_manager = SessionManager()

# 導出依賴
def get_session_manager():
    return session_manager