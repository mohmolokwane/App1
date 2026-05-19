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
        assert "version" in data
        assert data["version"] == "2.0.0"

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
        assert "User not found" in response.json()["detail"]
    
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
        assert "server error" in response.json()["detail"].lower()
    
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
    
    @patch('app.httpx.AsyncClient')
    def test_network_error_handling(self, mock_client):
        """Test network error handling"""
        # Setup mock to raise network error
        mock_async_client = AsyncMock()
        mock_async_client.get.side_effect = httpx.NetworkError("Network error")
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        response = client.get("/octocat?use_cache=false")
        assert response.status_code == 500
        # Network error should be caught and return 500
    
    def test_pagination_parameters(self):
        """Test pagination parameter validation"""
        # Invalid per_page (too high)
        response = client.get("/octocat?per_page=200")
        assert response.status_code == 400
        assert "per_page must be between 1 and 100" in response.json()["detail"]
        
        # Invalid per_page (too low)
        response = client.get("/octocat?per_page=0")
        assert response.status_code == 400
        
        # Invalid page
        response = client.get("/octocat?page=0")
        assert response.status_code == 400
    
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
        assert mock_async_client.get.call_count == 1
        
        # Second request - should be cached (no new API call)
        response2 = client.get("/octocat?use_cache=true")
        assert response2.status_code == 200
        # Note: mock_async_client.get.call_count remains 1 because cache is used
        assert mock_async_client.get.call_count == 1
    
    def test_invalid_username_format(self):
        """Test validation of invalid username formats"""
        # Username with special characters
        response = client.get("/invalid@username")
        assert response.status_code == 400
        assert "Invalid GitHub username format" in response.json()["detail"]
        
        # Username starting with hyphen
        response = client.get("/-invalid")
        assert response.status_code == 400
        
        # Username ending with hyphen
        response = client.get("/invalid-")
        assert response.status_code == 400
    
    def test_real_octocat_gists(self):
        """Test real GitHub API with octocat (integration test)"""
        # This test actually calls the GitHub API
        response = client.get("/octocat")
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "octocat"
        assert "gists" in data
        assert isinstance(data["gists"], list)
        assert "count" in data
        assert data["count"] == len(data["gists"])
        
        # Check structure of first gist if any exist
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
        # Clear cache first
        cache.clear()
        assert cache.size() == 0
        
        # Add items
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
        assert "documentation" in data
        assert "/docs" in data["documentation"]

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
        data = response.json()
        
        # Check required top-level fields
        required_fields = ["success", "username", "gists", "count", "pagination", "rate_limit", "cached", "timestamp"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        # Check rate limit fields
        assert "limit" in data["rate_limit"]
        assert "remaining" in data["rate_limit"]
        assert "reset" in data["rate_limit"]
        
        # Check gist fields
        if data["gists"]:
            gist = data["gists"][0]
            gist_fields = ["id", "description", "url", "files", "created_at", "updated_at"]
            for field in gist_fields:
                assert field in gist, f"Missing gist field: {field}"

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
        
        response = client.patch("/octocat")
        assert response.status_code == 405
    
    def test_options_request(self):
        """Test OPTIONS request for CORS"""
        response = client.options("/octocat")
        assert response.status_code == 200

class TestPaginationFunctionality:
    """Test pagination functionality"""
    
    @patch('app.httpx.AsyncClient')
    def test_pagination_links_parsing(self, mock_client):
        """Test that pagination links are properly parsed"""
        # Setup mock response with pagination links
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_GIST_RESPONSE
        mock_response.headers = {
            'x-ratelimit-limit': '5000',
            'x-ratelimit-remaining': '4999',
            'x-ratelimit-reset': str(int(datetime.now().timestamp() + 3600)),
            'link': '<https://api.github.com/gists?page=2>; rel="next", <https://api.github.com/gists?page=1>; rel="prev"'
        }
        
        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        response = client.get("/octocat?page=2&use_cache=false")
        data = response.json()
        
        assert "pagination" in data
        assert data["pagination"]["next"] is not None
        assert "rel=\"next\"" not in data["pagination"]["next"]  # Should be cleaned

class TestRateLimitHeaders:
    """Test rate limit header extraction"""
    
    @patch('app.httpx.AsyncClient')
    def test_rate_limit_extraction(self, mock_client):
        """Test that rate limit headers are properly extracted"""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_GIST_RESPONSE
        mock_response.headers = {
            'x-ratelimit-limit': '5000',
            'x-ratelimit-remaining': '4999',
            'x-ratelimit-reset': '1234567890'
        }
        
        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        response = client.get("/octocat?use_cache=false")
        data = response.json()
        
        assert data["rate_limit"]["limit"] == 5000
        assert data["rate_limit"]["remaining"] == 4999
        assert data["rate_limit"]["reset"] == 1234567890

# Run tests if file is executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])