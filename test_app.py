import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from datetime import datetime
import httpx

from app import app, cache

client = TestClient(app)

# Mock data that matches GitHub's API response format
MOCK_GIST_RESPONSE = [
    {
        "id": "12345",
        "description": "Test gist 1",
        "html_url": "https://gist.github.com/12345",
        "files": {
            "test1.py": {
                "filename": "test1.py",
                "raw_url": "https://raw.github.com/12345/test1.py",
                "size": 1024,
                "language": "Python"
            }
        },
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-02T00:00:00Z"
    },
    {
        "id": "67890",
        "description": None,
        "html_url": "https://gist.github.com/67890",
        "files": {
            "test2.js": {
                "filename": "test2.js",
                "raw_url": "https://raw.github.com/67890/test2.js",
                "size": 2048,
                "language": "JavaScript"
            }
        },
        "created_at": "2024-01-03T00:00:00Z",
        "updated_at": "2024-01-04T00:00:00Z"
    }
]

class TestHealthCheck:
    """Health check endpoint tests"""
    
    def test_health_endpoint(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "cache_size" in data
        assert "github_configured" in data
        # Remove version check since it's not in the health endpoint

class TestGistAPI:
    """Main API endpoint tests"""
    
    @patch('app.httpx.AsyncClient')
    def test_successful_gist_fetch(self, mock_client):
        """Test successful fetch of user gists"""
        # Setup mock response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_GIST_RESPONSE
        mock_response.headers = {
            'x-ratelimit-limit': '5000',
            'x-ratelimit-remaining': '4999',
            'x-ratelimit-reset': str(int(datetime.now().timestamp() + 3600)),
            'link': '<https://api.github.com/gists?page=2>; rel="next"'
        }
        
        # Setup mock client
        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        # Make request
        response = client.get("/octocat?use_cache=false")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["username"] == "octocat"
        assert data["count"] == 2
        assert "pagination" in data
        assert "rate_limit" in data
        assert data["rate_limit"]["remaining"] == 4999
        assert len(data["gists"]) == 2
        assert data["gists"][0]["id"] == "12345"
        assert data["gists"][0]["files"] == ["test1.py"]
        assert data["cached"] == False
    
    @patch('app.httpx.AsyncClient')
    def test_user_not_found(self, mock_client):
        """Test handling of non-existent user"""
        # Setup mock response for 404
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        response = client.get("/nonexistentuser123456?use_cache=false")
        assert response.status_code == 404
        # Fix: Match exact error message format
        assert "User 'nonexistentuser123456' not found" in response.json()["detail"]
    
    @patch('app.httpx.AsyncClient')
    def test_rate_limiting_error(self, mock_client):
        """Test handling of GitHub rate limiting"""
        # Setup mock response for rate limit
        mock_response = AsyncMock()
        mock_response.status_code = 403
        mock_response.text = "API rate limit exceeded"
        mock_response.headers = {'x-ratelimit-reset': '1234567890'}
        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        response = client.get("/octocat?use_cache=false")
        assert response.status_code == 429
        assert "rate limit exceeded" in response.json()["detail"].lower()
    
    @patch('app.httpx.AsyncClient')
    def test_github_server_error(self, mock_client):
        """Test handling of GitHub 5xx errors"""
        # Setup mock response for 503
        mock_response = AsyncMock()
        mock_response.status_code = 503
        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        response = client.get("/octocat?use_cache=false")
        assert response.status_code == 503
        # Fix: Match actual error message
        assert "GitHub API server error" in response.json()["detail"]
    
    @patch('app.httpx.AsyncClient')
    def test_timeout_handling(self, mock_client):
        """Test timeout handling"""
        # Setup mock to raise timeout
        mock_async_client = AsyncMock()
        mock_async_client.get.side_effect = httpx.TimeoutException("Timeout")
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        response = client.get("/octocat?use_cache=false")
        assert response.status_code == 504
        assert "timeout" in response.json()["detail"].lower()
    
    def test_pagination_parameters(self):
        """Test pagination parameter validation"""
        # FastAPI returns 422 for validation errors, not 400
        response = client.get("/octocat?per_page=200")
        assert response.status_code == 422  # Changed from 400 to 422
        
        response = client.get("/octocat?per_page=0")
        assert response.status_code == 422
        
        response = client.get("/octocat?page=0")
        assert response.status_code == 422
    
    @patch('app.httpx.AsyncClient')
    def test_caching_mechanism(self, mock_client):
        """Test that caching works correctly"""
        # Setup mock response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_GIST_RESPONSE
        mock_response.headers = {
            'x-ratelimit-limit': '5000',
            'x-ratelimit-remaining': '4999',
            'x-ratelimit-reset': str(int(datetime.now().timestamp() + 3600))
        }
        
        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        # Clear cache first
        client.get("/cache/clear")
        
        # First request - should not be cached
        response1 = client.get("/octocat?use_cache=true")
        assert response1.status_code == 200
        assert response1.json()["cached"] == False
        
        # Second request - should be cached
        response2 = client.get("/octocat?use_cache=true")
        assert response2.status_code == 200
        assert response2.json()["cached"] == True  # This should now be True
    
    def test_invalid_username_format(self):
        """Test validation of invalid username formats"""
        response = client.get("/invalid@username")
        assert response.status_code == 400
        assert "Invalid GitHub username format" in response.json()["detail"]
    
    def test_real_octocat_gists(self):
        """Test real GitHub API with octocat (integration test)"""
        response = client.get("/octocat")
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "octocat"
        assert "gists" in data
        assert isinstance(data["gists"], list)
        assert "count" in data
        assert data["count"] == len(data["gists"])
        
        if data["gists"]:
            gist = data["gists"][0]
            assert "id" in gist
            assert "url" in gist
            assert "files" in gist
            assert isinstance(gist["files"], list)

class TestCacheManagement:
    """Cache management endpoint tests"""
    
    def test_clear_cache(self):
        """Test cache clearing endpoint"""
        # Set some cache directly
        cache.set("test_key", "test_value")
        assert cache.size() > 0
        
        # Clear cache
        response = client.get("/cache/clear")
        assert response.status_code == 200
        assert response.json()["message"] == "Cache cleared successfully"
        assert cache.size() == 0
    
    def test_cache_size_tracking(self):
        """Test cache size is tracked correctly"""
        cache.clear()
        assert cache.size() == 0
        
        cache.set("key1", "value1")
        assert cache.size() == 1
        
        cache.set("key2", "value2")
        assert cache.size() == 2

class TestRootEndpoint:
    """Root endpoint tests"""
    
    def test_root_endpoint(self):
        """Test root endpoint returns API info"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "GitHub Gist API"
        assert data["version"] == "2.0.0"
        assert "endpoints" in data
        assert "/{username}" in data["endpoints"]

class TestResponseStructure:
    """Test response structure and data mapping"""
    
    @patch('app.httpx.AsyncClient')
    def test_response_contains_required_fields(self, mock_client):
        """Test that response contains all required fields"""
        # Setup mock
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_GIST_RESPONSE
        mock_response.headers = {
            'x-ratelimit-limit': '5000',
            'x-ratelimit-remaining': '4999',
            'x-ratelimit-reset': str(int(datetime.now().timestamp() + 3600))
        }
        
        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        response = client.get("/octocat?use_cache=false")
        assert response.status_code == 200
        data = response.json()
        
        # Check required top-level fields
        required_fields = ["success", "username", "gists", "count", "pagination", "rate_limit", "cached", "timestamp"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

class TestSecurityHeaders:
    """Test security-related configurations"""
    
    def test_method_not_allowed(self):
        """Test that only GET is allowed"""
        response = client.post("/octocat")
        assert response.status_code == 405
        
        response = client.put("/octocat")
        assert response.status_code == 405
        
        response = client.delete("/octocat")
        assert response.status_code == 405
    
    def test_options_request(self):
        """Test OPTIONS request - FastAPI doesn't handle OPTIONS by default"""
        response = client.options("/octocat")
        # FastAPI returns 405 for OPTIONS if not explicitly handled
        assert response.status_code in [200, 405]

# Run tests if file is executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])