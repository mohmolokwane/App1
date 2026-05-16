import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from functools import lru_cache
import re

import httpx
from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # Optional: for higher rate limits
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))
MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", "100"))
DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_PAGE_SIZE", "30"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10.0"))

# Pydantic models for response structure
class GistResponse(BaseModel):
    id: str
    description: Optional[str]
    url: str
    files: List[str]
    created_at: Optional[str]
    updated_at: Optional[str]

class ApiResponse(BaseModel):
    success: bool = True
    username: str
    gists: List[GistResponse]
    count: int
    pagination: Dict[str, Optional[str]]
    rate_limit: Dict[str, int]
    cached: bool
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

# Simple in-memory cache
class Cache:
    def __init__(self):
        self.data = {}
        self.timestamps = {}
    
    def get(self, key: str) -> Optional[Any]:
        if key in self.data:
            if datetime.now() - self.timestamps[key] < timedelta(seconds=CACHE_TTL_SECONDS):
                logger.debug(f"Cache hit: {key}")
                return self.data[key]
            else:
                logger.debug(f"Cache expired: {key}")
                del self.data[key]
                del self.timestamps[key]
        return None
    
    def set(self, key: str, value: Any):
        self.data[key] = value
        self.timestamps[key] = datetime.now()
        logger.debug(f"Cache set: {key}")
    
    def clear(self):
        self.data.clear()
        self.timestamps.clear()
        logger.info("Cache cleared")

cache = Cache()

app = FastAPI(
    title="GitHub Gist API",
    description="API to fetch GitHub user's public gists",
    version="2.0.0"
)

def validate_github_username(username: str) -> bool:
    """Validate GitHub username format"""
    pattern = r'^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$'
    return bool(re.match(pattern, username))

async def fetch_gists_from_github(username: str, page: int, per_page: int) -> tuple:
    """Fetch gists from GitHub API"""
    url = f"https://api.github.com/users/{username}/gists"
    params = {"page": page, "per_page": per_page}
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "GitHub-Gist-API"
    }
    
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(url, params=params, headers=headers)
        
        # Handle GitHub API errors
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"User '{username}' not found")
        elif response.status_code == 403 and "rate limit" in response.text.lower():
            raise HTTPException(status_code=429, detail="GitHub API rate limit exceeded")
        elif response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="GitHub API error")
        
        # Extract rate limit info
        rate_limits = {
            "limit": int(response.headers.get('x-ratelimit-limit', 0)),
            "remaining": int(response.headers.get('x-ratelimit-remaining', 0)),
            "reset": int(response.headers.get('x-ratelimit-reset', 0))
        }
        
        # Parse pagination links
        pagination = {"next": None, "prev": None, "first": None, "last": None}
        link_header = response.headers.get('link', '')
        
        for link in link_header.split(','):
            part = link.strip().split(';')
            if len(part) == 2:
                url_part = part[0].strip('<> ')
                rel_part = part[1].strip().split('=')[1].strip('"')
                if rel_part in pagination:
                    pagination[rel_part] = url_part
        
        # Parse gists data
        gists_data = response.json()
        
        # Map to clean response
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
    """API information"""
    return {
        "message": "GitHub Gist API",
        "version": "2.0.0",
        "endpoints": {
            "/{username}": "Get user's public gists",
            "/{username}?page=1&per_page=30": "With pagination",
            "/health": "Health check",
            "/cache/clear": "Clear cache"
        },
        "examples": {
            "octocat": "/octocat",
            "pagination": "/octocat?page=1&per_page=5",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "cache_size": len(cache.data),
        "github_configured": bool(GITHUB_TOKEN)
    }

@app.get("/cache/clear")
async def clear_cache():
    """Clear the cache"""
    cache.clear()
    return {"message": "Cache cleared", "timestamp": datetime.utcnow().isoformat()}

@app.get("/{username}")
async def get_user_gists(
    username: str = Path(..., description="GitHub username"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    use_cache: bool = Query(True, description="Use cached response")
) -> ApiResponse:
    """
    Get all public gists for a GitHub user
    
    - **username**: GitHub username (e.g., octocat)
    - **page**: Page number for pagination
    - **per_page**: Number of items per page (max 100)
    - **use_cache**: Whether to use cached response
    """
    
    # Validate username
    if not validate_github_username(username):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid GitHub username format: '{username}'. "
                   f"Usernames can only contain alphanumeric characters and hyphens."
        )
    
    # Check cache
    cache_key = f"{username}:{page}:{per_page}"
    if use_cache:
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.info(f"Returning cached data for {username}")
            return ApiResponse(**cached_data, cached=True)
    
    # Fetch from GitHub
    try:
        logger.info(f"Fetching gists for {username} (page={page}, per_page={per_page})")
        gists, pagination, rate_limits = await fetch_gists_from_github(username, page, per_page)
        
        # Prepare response
        response_data = {
            "username": username,
            "gists": [gist.dict() for gist in gists],
            "count": len(gists),
            "pagination": pagination,
            "rate_limit": rate_limits,
            "cached": False,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Cache the response
        if use_cache:
            cache.set(cache_key, response_data)
        
        return ApiResponse(**response_data)
        
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching gists for {username}")
        raise HTTPException(status_code=504, detail="GitHub API timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")