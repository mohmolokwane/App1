import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from enum import Enum
from dataclasses import dataclass, asdict
from functools import wraps
import re

import httpx
from fastapi import FastAPI, HTTPException, Request, Depends, Path
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, validator
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
GITHUB_API_BASE_URL = os.getenv("GITHUB_API_BASE_URL", "https://api.github.com")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # Optional: for higher rate limits
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))
MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", "100"))
DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_PAGE_SIZE", "30"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10.0"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# Data models for better structure
class GistFile(BaseModel):
    filename: str
    raw_url: Optional[str] = None
    size: Optional[int] = None
    language: Optional[str] = None

class GistResponse(BaseModel):
    id: str
    description: Optional[str] = None
    url: str
    files: List[str]
    file_details: Optional[Dict[str, GistFile]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_public: bool = True
    comments: int = 0

class ApiResponse(BaseModel):
    success: bool
    username: str
    gists: List[GistResponse]
    count: int
    pagination: Dict[str, Optional[str]]
    rate_limit: Dict[str, int]
    cache_info: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class GitHubErrorType(str, Enum):
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"

@dataclass
class GitHubRateLimit:
    limit: int
    remaining: int
    reset: datetime
    
    def to_dict(self) -> Dict[str, int]:
        return {
            "limit": self.limit,
            "remaining": self.remaining,
            "resets_at": int(self.reset.timestamp())
        }

# Enhanced caching with TTL and size limits
class EnhancedCache:
    def __init__(self, max_size: int = 100, ttl_seconds: int = 300):
        self.cache: Dict[str, tuple] = {}
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        logger.info(f"Cache initialized with max_size={max_size}, ttl={ttl_seconds}s")
    
    def get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            data, timestamp = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.ttl_seconds):
                logger.debug(f"Cache hit for key: {key}")
                return data
            else:
                logger.debug(f"Cache expired for key: {key}")
                del self.cache[key]
        return None
    
    def set(self, key: str, value: Any):
        if len(self.cache) >= self.max_size:
            # Remove oldest entry
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
            del self.cache[oldest_key]
            logger.debug(f"Cache evicted oldest entry: {oldest_key}")
        
        self.cache[key] = (value, datetime.now())
        logger.debug(f"Cache set for key: {key}")
    
    def clear(self):
        self.cache.clear()
        logger.info("Cache cleared")

cache = EnhancedCache(max_size=100, ttl_seconds=CACHE_TTL_SECONDS)

app = FastAPI(
    title="GitHub Gist API",
    description="Production-ready API for fetching GitHub user gists with rate limiting, caching, and error handling",
    version="2.0.0"
)

# Security middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv("ALLOWED_HOSTS", "*").split(","))

def validate_github_username(username: str) -> bool:
    """Validate GitHub username format"""
    # GitHub username rules: alphanumeric and hyphens, max 39 chars, can't start/end with hyphen
    pattern = r'^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$'
    return bool(re.match(pattern, username))

@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError))
)
async def make_github_request(client: httpx.AsyncClient, url: str, params: Dict = None) -> httpx.Response:
    """Make authenticated GitHub API request with retry logic"""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "GitHub-Gist-API/2.0"
    }
    
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
        logger.debug("Using authenticated GitHub API request")
    
    response = await client.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
    
    # Log rate limit info
    if 'x-ratelimit-limit' in response.headers:
        logger.info(f"Rate limit: {response.headers['x-ratelimit-limit']}/{response.headers.get('x-ratelimit-remaining', '?')}")
    
    return response

async def extract_rate_limits(response: httpx.Response) -> GitHubRateLimit:
    """Extract rate limit information from response headers"""
    return GitHubRateLimit(
        limit=int(response.headers.get('x-ratelimit-limit', 0)),
        remaining=int(response.headers.get('x-ratelimit-remaining', 0)),
        reset=datetime.fromtimestamp(int(response.headers.get('x-ratelimit-reset', 0)))
    )

def map_github_gist_to_response(gist: Dict) -> GistResponse:
    """Map GitHub API response to our clean DTO"""
    files_data = gist.get('files', {})
    
    # Extract file details if available
    file_details = {}
    for filename, file_info in files_data.items():
        file_details[filename] = GistFile(
            filename=filename,
            raw_url=file_info.get('raw_url'),
            size=file_info.get('size'),
            language=file_info.get('language')
        )
    
    return GistResponse(
        id=gist.get('id'),
        description=gist.get('description', 'No description provided'),
        url=gist.get('html_url'),
        files=list(files_data.keys()),
        file_details=file_details if file_details else None,
        created_at=datetime.fromisoformat(gist.get('created_at', '').replace('Z', '+00:00')) if gist.get('created_at') else None,
        updated_at=datetime.fromisoformat(gist.get('updated_at', '').replace('Z', '+00:00')) if gist.get('updated_at') else None,
        comments=gist.get('comments', 0)
    )

def handle_github_error(response: httpx.Response) -> HTTPException:
    """Centralized error handling for GitHub API responses"""
    status_code = response.status_code
    
    if status_code == 401:
        return HTTPException(status_code=502, detail="GitHub API authentication failed")
    elif status_code == 403:
        if 'rate limit' in response.text.lower():
            reset_time = response.headers.get('x-ratelimit-reset')
            return HTTPException(
                status_code=429, 
                detail=f"GitHub API rate limit exceeded. Resets at {reset_time}"
            )
        return HTTPException(status_code=403, detail="Access forbidden by GitHub API")
    elif status_code == 404:
        return HTTPException(status_code=404, detail="User not found on GitHub")
    elif status_code >= 500:
        return HTTPException(
            status_code=503, 
            detail=f"GitHub API server error (status {status_code})"
        )
    else:
        return HTTPException(
            status_code=502, 
            detail=f"GitHub API error: {response.status_code}"
        )

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "GitHub Gist API",
        "version": "2.0.0",
        "endpoints": {
            "/{username}": "Get user's public gists",
            "/health": "Health check",
            "/cache/clear": "Clear cache (admin)"
        },
        "documentation": "/docs",
        "example": "/octocat?page=1&per_page=30"
    }

@app.get("/health")
async def health_check():
    """Enhanced health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "cache_size": len(cache.cache),
        "github_configured": bool(GITHUB_TOKEN),
        "version": "2.0.0"
    }

@app.get("/cache/clear")
async def clear_cache():
    """Admin endpoint to clear cache"""
    cache.clear()
    return {"message": "Cache cleared successfully"}

@app.get("/{username}")
async def get_user_gists(
    username: str = Path(..., description="GitHub username (e.g., octocat)"),
    page: int = 1,
    per_page: int = DEFAULT_PAGE_SIZE,
    use_cache: bool = True
) -> JSONResponse:
    """
    Get all public gists for a GitHub user with pagination support
    
    - **username**: GitHub username (e.g., octocat)
    - **page**: Page number for pagination (default: 1)
    - **per_page**: Items per page (default: 30, max: 100)
    - **use_cache**: Whether to use cached response (default: true)
    """
    
    # Validate username format
    if not validate_github_username(username):
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid GitHub username format: '{username}'. Usernames can only contain alphanumeric characters and hyphens, and cannot start or end with a hyphen."
        )
    
    # Validate pagination parameters
    if per_page < 1 or per_page > MAX_PAGE_SIZE:
        raise HTTPException(
            status_code=400, 
            detail=f"per_page must be between 1 and {MAX_PAGE_SIZE}"
        )
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    
    cache_key = f"{username}:{page}:{per_page}"
    
    # Check cache
    if use_cache:
        cached_response = cache.get(cache_key)
        if cached_response:
            logger.info(f"Returning cached response for {username}")
            return JSONResponse(content=cached_response)
    
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            url = f"{GITHUB_API_BASE_URL}/users/{username}/gists"
            params = {
                "page": page,
                "per_page": per_page
            }
            
            logger.info(f"Fetching gists for user {username} (page={page}, per_page={per_page})")
            response = await make_github_request(client, url, params)
            
            # Handle error responses
            if response.status_code != 200:
                raise handle_github_error(response)
            
            # Extract pagination info
            gists_data = response.json()
            rate_limits = await extract_rate_limits(response)
            
            # Map to clean response objects
            mapped_gists = [map_github_gist_to_response(gist) for gist in gists_data]
            
            # Extract pagination links
            link_header = response.headers.get('link', '')
            pagination = {
                "next": None,
                "prev": None,
                "first": None,
                "last": None
            }
            
            for link in link_header.split(','):
                part = link.strip().split(';')
                if len(part) == 2:
                    url_part = part[0].strip('<> ')
                    rel_part = part[1].strip().split('=')[1].strip('"')
                    if rel_part in pagination:
                        pagination[rel_part] = url_part
            
            # Prepare response
            response_data = {
                "success": True,
                "username": username,
                "gists": [gist.dict() for gist in mapped_gists],
                "count": len(mapped_gists),
                "pagination": pagination,
                "rate_limit": rate_limits.to_dict(),
                "cache_info": {
                    "used_cache": False,
                    "cache_key": cache_key if use_cache else None,
                    "ttl_seconds": CACHE_TTL_SECONDS
                },
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Cache the response
            if use_cache:
                cache.set(cache_key, response_data)
            
            return JSONResponse(content=response_data)
            
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching gists for {username}")
        raise HTTPException(status_code=504, detail="GitHub API request timeout")
    except httpx.NetworkError as e:
        logger.error(f"Network error: {str(e)}")
        raise HTTPException(status_code=503, detail=f"Network error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error")

@app.on_event("startup")
async def startup_event():
    logger.info("Starting GitHub Gist API server v2.0.0")
    logger.info(f"Configuration: CACHE_TTL={CACHE_TTL_SECONDS}s, MAX_PAGE_SIZE={MAX_PAGE_SIZE}, TIMEOUT={REQUEST_TIMEOUT}s")
    if GITHUB_TOKEN:
        logger.info("GitHub token configured - higher rate limits available")
    else:
        logger.warning("No GitHub token configured - rate limits will be restricted to 60 requests/hour")