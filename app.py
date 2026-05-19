import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import re

import httpx
from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))
MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", "100"))
DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_PAGE_SIZE", "30"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10.0"))

class GistResponse(BaseModel):
    id: str
    description: Optional[str]
    url: str
    files: List[str]
    created_at: Optional[str]
    updated_at: Optional[str)

class Cache:
    def __init__(self):
        self.data = {}
        self.timestamps = {}
    
    def get(self, key: str) -> Optional[Any]:
        if key in self.data:
            if datetime.now() - self.timestamps[key] < timedelta(seconds=CACHE_TTL_SECONDS):
                return self.data[key]
            else:
                del self.data[key]
                del self.timestamps[key]
        return None
    
    def set(self, key: str, value: Any):
        self.data[key] = value
        self.timestamps[key] = datetime.now()
    
    def clear(self):
        self.data.clear()
        self.timestamps.clear()
    
    def size(self):
        return len(self.data)

cache = Cache()
app = FastAPI(title="GitHub Gist API", version="2.0.0")

def validate_github_username(username: str) -> bool:
    pattern = r'^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$'
    return bool(re.match(pattern, username))

async def fetch_gists_from_github(username: str, page: int, per_page: int):
    url = f"https://api.github.com/users/{username}/gists"
    params = {"page": page, "per_page": per_page}
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "GitHub-Gist-API"}
    
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(url, params=params, headers=headers)
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"User '{username}' not found")
        elif response.status_code == 403 and "rate limit" in response.text.lower():
            raise HTTPException(status_code=429, detail="GitHub API rate limit exceeded")
        elif response.status_code == 503:
            raise HTTPException(status_code=503, detail="GitHub API server error")
        elif response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="GitHub API error")
        
        rate_limits = {
            "limit": int(response.headers.get('x-ratelimit-limit', 0)),
            "remaining": int(response.headers.get('x-ratelimit-remaining', 0)),
            "reset": int(response.headers.get('x-ratelimit-reset', 0))
        }
        
        pagination = {"next": None, "prev": None, "first": None, "last": None}
        link_header = response.headers.get('link', '')
        for link in link_header.split(','):
            part = link.strip().split(';')
            if len(part) == 2:
                url_part = part[0].strip('<> ')
                rel_part = part[1].strip().split('=')[1].strip('"')
                if rel_part in pagination:
                    pagination[rel_part] = url_part
        
        # Parse JSON response
        gists_data = response.json()
        
        mapped_gists = []
        for gist in gists_data:
            mapped_gists.append(GistResponse(
                id=gist.get("id"),
                description=gist.get("description") or "",
                url=gist.get("html_url"),
                files=list(gist.get("files", {}).keys()),
                created_at=gist.get("created_at"),
                updated_at=gist.get("updated_at")
            ))
        
        return mapped_gists, pagination, rate_limits

@app.get("/")
async def root():
    return {
        "message": "GitHub Gist API",
        "version": "2.0.0",
        "endpoints": {
            "/{username}": "Get user's public gists",
            "/health": "Health check",
            "/cache/clear": "Clear cache"
        }
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "cache_size": cache.size(),
        "github_configured": bool(GITHUB_TOKEN)
    }

@app.get("/cache/clear")
async def clear_cache():
    cache.clear()
    return {"message": "Cache cleared successfully"}

@app.get("/{username}")
async def get_user_gists(
    username: str = Path(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    use_cache: bool = Query(True)
):
    if not validate_github_username(username):
        raise HTTPException(status_code=400, detail=f"Invalid GitHub username format: '{username}'")
    
    cache_key = f"{username}:{page}:{per_page}"
    if use_cache:
        cached_data = cache.get(cache_key)
        if cached_data:
            return JSONResponse(content=cached_data)
    
    try:
        gists, pagination, rate_limits = await fetch_gists_from_github(username, page, per_page)
        
        response_data = {
            "success": True,
            "username": username,
            "gists": [gist.model_dump() for gist in gists],
            "count": len(gists),
            "pagination": pagination,
            "rate_limit": rate_limits,
            "cached": False,
            "timestamp": datetime.now().isoformat()
        }
        
        if use_cache:
            cache.set(cache_key, response_data)
        
        return JSONResponse(content=response_data)
        
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="GitHub API request timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))