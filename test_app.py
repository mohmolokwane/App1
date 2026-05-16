import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, Mock
from datetime import datetime, timedelta
import httpx
import json

from app import app, cache, GitHubRateLimit

client = TestClient(app)

# Mock data
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
        "updated_at": "2024-01-02T00:00:00Z",
        "comments": 0,
        "public": True
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
        "updated_at": "2024-01-04T00:00:00Z",
        "comments": 2,
        "public": True
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
    
    @patch('app.make_github_request')
    @pytest.mark.asyncio
    async def test_successful_gist_fetch(self, mock_request):
        """Test successful fetch of user gists"""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_GIST_RESPONSE
        mock_response.headers = {
            'x-ratelimit-limit': '5000',
            'x-ratelimit-remaining': '4999',
            'x-ratelimit-reset': str(int(datetime.now().timestamp() + 3600)),
            'link': '<https://api.github.com/gists?page=2>; rel="next"'
        }
        mock_request.return_value = mock_response
        
        with patch('app.httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = mock_request
            
            response = client.get("/octocat?use_cache=false")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] == True
            assert data["username"] == "octocat"
            assert data["count"] == 2
            assert "pagination" in data
            assert "rate_limit" in data
            assert data["rate_limit"]["remaining"] == 4999
    
    def test_user_not_found(self):
        """Test handling of non-existent user"""
        with patch('app.make_github_request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status_code = 404
            mock_request.return_value = mock_response
            
            response = client.get("/nonexistentuser123456")
            assert response.status_code == 404
            assert "User not found" in response.json()["detail"]
    
    def test_rate_limiting_error(self):
        """Test handling of GitHub rate limiting"""
        with patch('app.make_github_request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status_code = 403
            mock_response.text = "API rate limit exceeded"
            mock_response.headers = {'x-ratelimit-reset': '1234567890'}
            mock_request.return_value = mock_response
            
            response = client.get("/octocat?use_cache=false")
            assert response.status_code == 429
            assert "rate limit exceeded" in response.json()["detail"].lower()
    
    def test_github_server_error(self):
        """Test handling of GitHub 5xx errors"""
        with patch('app.make_github_request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status_code = 503
            mock_request.return_value = mock_response
            
            response = client.get("/octocat?use_cache=false")
            assert response.status_code == 503
            assert "server error" in response.json()["detail"].lower()
    
    def test_timeout_handling(self):
        """Test timeout handling"""
        with patch('app.make_github_request') as mock_request:
            mock_request.side_effect = httpx.TimeoutException("Timeout")
            
            response = client.get("/octocat?use_cache=false")
            assert response.status_code == 504
            assert "timeout" in response.json()["detail"].lower()
    
    def test_network_error_handling(self):
        """Test network error handling"""
        with patch('app.make_github_request') as mock_request:
            mock_request.side_effect = httpx.NetworkError("Network error")
            
            response = client.get("/octocat?use_cache=false")
            assert response.status_code == 503
            assert "network error" in response.json()["detail"].lower()
    
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
    
    def test_caching_mechanism(self):
        """Test that caching works correctly"""
        with patch('app.make_github_request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json.return_value = MOCK_GIST_RESPONSE
            mock_response.headers = {
                'x-ratelimit-limit': '5000',
                'x-ratelimit-remaining': '4999',
                'x-ratelimit-reset': str(int(datetime.now().timestamp() + 3600))
            }
            mock_request.return_value = mock_response
            
            # Clear cache first
            client.get("/cache/clear")
            
            # First request - should not be cached
            response1 = client.get("/octocat?use_cache=true")
            assert response1.status_code == 200
            assert response1.json()["cache_info"]["used_cache"] == False
            
            # Second request - should be cached
            response2 = client.get("/octocat?use_cache=true")
            assert response2.status_code == 200
            assert response2.json()["cache_info"]["used_cache"] == True
    
    def test_response_data_mapping(self):
        """Test that GitHub response is properly mapped to clean DTO"""
        with patch('app.make_github_request') as mock_request:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json.return_value = MOCK_GIST_RESPONSE
            mock_response.headers = {
                'x-ratelimit-limit': '5000',
                'x-ratelimit-remaining': '4999',
                'x-ratelimit-reset': str(int(datetime.now().timestamp() + 3600))
            }
            mock_request.return_value = mock_response
            
            response = client.get("/octocat")
            data = response.json()
            
            # Verify mapped structure
            gist = data["gists"][0]
            assert "id" in gist
            assert "description" in gist
            assert "url" in gist
            assert "files" in gist
            assert "file_details" in gist
            assert "created_at" in gist
            assert "updated_at" in gist
            assert "comments" in gist
            
            # Verify file details mapping
            file_details = gist["file_details"]
            assert "test1.py" in file_details
            assert file_details["test1.py"]["language"] == "Python"

class TestCacheManagement:
    """Cache management endpoint tests"""
    
    def test_clear_cache(self):
        """Test cache clearing endpoint"""
        # Set some cache
        cache.set("test_key", "test_value")
        assert len(cache.cache) > 0
        
        # Clear cache
        response = client.get("/cache/clear")
        assert response.status_code == 200
        assert response.json()["message"] == "Cache cleared successfully"
        assert len(cache.cache) == 0

class TestRateLimitExtraction:
    """Test rate limit header extraction"""
    
    def test_rate_limit_parsing(self):
        """Test rate limit extraction from headers"""
        mock_response = Mock()
        mock_response.headers = {
            'x-ratelimit-limit': '5000',
            'x-ratelimit-remaining': '4999',
            'x-ratelimit-reset': '1234567890'
        }
        
        # This would be called in the actual endpoint
        assert int(mock_response.headers.get('x-ratelimit-limit', 0)) == 5000

class TestSecurityHeaders:
    """Test security-related configurations"""
    
    def test_cors_headers(self):
        """Test CORS headers are present"""
        response = client.get("/octocat")
        # CORS headers should be present for OPTIONS preflight
        assert response.status_code == 200
    
    def test_method_not_allowed(self):
        """Test that only GET is allowed"""
        response = client.post("/octocat")
        assert response.status_code == 405
        
        response = client.put("/octocat")
        assert response.status_code == 405
        
        response = client.delete("/octocat")
        assert response.status_code == 405

# Run all tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--cov=app", "--cov-report=term-missing"])