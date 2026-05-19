import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from datetime import datetime

from app import app, cache

client = TestClient(app)

MOCK_GIST_RESPONSE = [
    {
        "id": "12345",
        "description": "Test gist 1",
        "html_url": "https://gist.github.com/12345",
        "files": {"test1.py": {}},
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-02T00:00:00Z"
    },
    {
        "id": "67890",
        "description": None,
        "html_url": "https://gist.github.com/67890",
        "files": {"test2.js": {}},
        "created_at": "2024-01-03T00:00:00Z",
        "updated_at": "2024-01-04T00:00:00Z"
    }
]

class TestHealthCheck:
    def test_health_endpoint(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "cache_size" in data

class TestGistAPI:
    @patch('app.httpx.AsyncClient')
    def test_successful_gist_fetch(self, mock_client):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: MOCK_GIST_RESPONSE
        mock_response.headers = {
            'x-ratelimit-limit': '5000',
            'x-ratelimit-remaining': '4999',
            'x-ratelimit-reset': str(int(datetime.now().timestamp() + 3600)),
        }
        
        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        response = client.get("/octocat?use_cache=false")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["username"] == "octocat"
        assert len(data["gists"]) == 2
    
    @patch('app.httpx.AsyncClient')
    def test_user_not_found(self, mock_client):
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        response = client.get("/nonexistentuser123456?use_cache=false")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
    
    @patch('app.httpx.AsyncClient')
    def test_rate_limiting_error(self, mock_client):
        mock_response = AsyncMock()
        mock_response.status_code = 403
        mock_response.text = "API rate limit exceeded"
        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        response = client.get("/octocat?use_cache=false")
        assert response.status_code == 429
    
    @patch('app.httpx.AsyncClient')
    def test_github_server_error(self, mock_client):
        mock_response = AsyncMock()
        mock_response.status_code = 503
        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        response = client.get("/octocat?use_cache=false")
        assert response.status_code == 503
    
    @patch('app.httpx.AsyncClient')
    def test_timeout_handling(self, mock_client):
        import httpx
        mock_async_client = AsyncMock()
        mock_async_client.get.side_effect = httpx.TimeoutException("Timeout")
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        response = client.get("/octocat?use_cache=false")
        assert response.status_code == 504
    
    def test_pagination_parameters(self):
        response = client.get("/octocat?per_page=200")
        assert response.status_code == 422
        
        response = client.get("/octocat?per_page=0")
        assert response.status_code == 422
    
    @patch('app.httpx.AsyncClient')
    def test_caching_mechanism(self, mock_client):
        """Test that caching works correctly"""
        # Clear cache before test
        client.get("/cache/clear")
        
        # Setup mock response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: MOCK_GIST_RESPONSE
        mock_response.headers = {
            'x-ratelimit-limit': '5000',
            'x-ratelimit-remaining': '4999',
            'x-ratelimit-reset': str(int(datetime.now().timestamp() + 3600))
        }
        
        mock_async_client = AsyncMock()
        mock_async_client.get.return_value = mock_response
        mock_client.return_value.__aenter__.return_value = mock_async_client
        
        # First request - should call API and not be cached
        response1 = client.get("/octocat?use_cache=true")
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["cached"] == False
        
        # Second request - should use cache
        response2 = client.get("/octocat?use_cache=true")
        assert response2.status_code == 200
        data2 = response2.json()
        
        # The second response should come from cache
        assert data2["cached"] == True
    
    def test_invalid_username_format(self):
        response = client.get("/invalid@username")
        assert response.status_code == 400
    
    def test_real_octocat_gists(self):
        """Test real GitHub API with octocat (integration test)"""
        # Clear cache to ensure fresh fetch
        client.get("/cache/clear")
        
        response = client.get("/octocat")
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "octocat"
        assert "gists" in data
        assert data["cached"] == False
        
        # Second request should be cached
        response2 = client.get("/octocat")
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["cached"] == True  # This should be True for cached response

class TestCacheManagement:
    def test_clear_cache(self):
        cache.set("test_key", "test_value")
        assert cache.size() > 0
        
        response = client.get("/cache/clear")
        assert response.status_code == 200
        assert cache.size() == 0
    
    def test_cache_size_tracking(self):
        cache.clear()
        assert cache.size() == 0
        
        cache.set("key1", "value1")
        assert cache.size() == 1

class TestRootEndpoint:
    def test_root_endpoint(self):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "GitHub Gist API"
        assert data["version"] == "2.0.0"

class TestResponseStructure:
    @patch('app.httpx.AsyncClient')
    def test_response_contains_required_fields(self, mock_client):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: MOCK_GIST_RESPONSE
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
        
        required_fields = ["success", "username", "gists", "count", "pagination", "rate_limit", "cached", "timestamp"]
        for field in required_fields:
            assert field in data

class TestSecurityHeaders:
    def test_method_not_allowed(self):
        response = client.post("/octocat")
        assert response.status_code == 405
        
        response = client.put("/octocat")
        assert response.status_code == 405
        
        response = client.delete("/octocat")
        assert response.status_code == 405

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])