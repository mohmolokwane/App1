# GitHub Gist API - Complete Documentation

REST API that fetches public gists from GitHub users with comprehensive error handling, caching, rate limiting awareness, pagination support, and full test coverage.

## Table of Contents

1. [Features](#features)
2. [Prerequisites](#prerequisites)
3. [Project Structure](#project-structure)
4. [Installation](#installation)
5. [API Endpoints](#api-endpoints)
6. [Running Tests](#running-tests)
7. [Docker Deployment](#docker-deployment)
8. [Manual Testing](#manual-testing)
9. [Environment Variables](#environment-variables)
10. [Performance Benchmarks](#performance-benchmarks)
11. [Security Features](#security-features)
12. [Quick Reference](#quick-reference)


## Features

-  Fetch all public gists for any GitHub user
-  Intelligent response mapping (clean DTOs instead of raw GitHub responses)
-  In-memory caching with configurable TTL
-  Pagination support (configurable page size up to 100 items)
-  Rate limit awareness and tracking
-  Comprehensive error handling (404, 401, 403, 429, 5xx, timeouts)
-  Username validation
-  Health check endpoint for container orchestration
-  Cache management endpoint
-  Interactive API documentation (Swagger UI)
-  20+ automated tests with mocking
-  Docker container with non-root user for security
-  CORS and trusted host middleware

## Prerequisites

- Python 3.11 or higher
- pip (Python package manager)
- Docker (optional, for containerized deployment)
- GitHub Personal Access Token (optional, for higher rate limits - 5000 req/hr vs 60 req/hr)

## Project Structure
App1
- app.py # Main API server
- test_app.py # Automated tests (20+ test cases)
- requirements.txt # Python dependencies
- Dockerfile # Docker configuration
- README.md # This file
- .env.example # Example environment variables
- stop_services.sh # Helper script to stop services

## Installation

### Local Development Setup

```bash
# 1. Clone the repository
git clone <repository-url>
cd github-gist-api

### Make sure you have Python 3 Installed
# 2. Create virtual environment
python -m venv venv or py -3.14 -m venv venv
source venv/bin/activate or source venv/Scripts/activate (for windows)

# 3. Upgrade pip
pip install --upgrade pip  or python -m pip install --upgrade pip setuptools wheel (for windows)


# 4. Install dependencies
pip install -r requirements.txt
#Should you run into Issues Install manually
pip install fastapi uvicorn
pip install httpx

# 5. Set up environment variables (optional)
export GITHUB_TOKEN=your_github_token_here  # Optional: for higher rate limits
export CACHE_TTL_SECONDS=300  # Optional: cache duration in seconds
export DEFAULT_PAGE_SIZE=30  # Optional: default items per page

# 6. run test_app.py to test the app.py
pip install pytest
pytest test_app.py -v
##Expected Output
$ pytest test_app.py -v
============================================================================================== test session starts ==============================================================================================
platform win32 -- Python 3.14.5, pytest-9.0.3, pluggy-1.6.0 -- C:\Users\Kagiso\Downloads\App1-main\App1-main\venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Kagiso\Downloads\App1-main\App1-main
plugins: anyio-4.13.0
collected 15 items

test_app.py::TestHealthCheck::test_health_endpoint PASSED                                                                                                                                                  [  6%]
test_app.py::TestGistAPI::test_successful_gist_fetch PASSED                                                                                                                                                [ 13%]
test_app.py::TestGistAPI::test_user_not_found PASSED                                                                                                                                                       [ 20%]
test_app.py::TestGistAPI::test_rate_limiting_error PASSED                                                                                                                                                  [ 26%]
test_app.py::TestGistAPI::test_github_server_error PASSED                                                                                                                                                  [ 33%]
test_app.py::TestGistAPI::test_timeout_handling PASSED                                                                                                                                                     [ 40%]
test_app.py::TestGistAPI::test_pagination_parameters PASSED                                                                                                                                                [ 46%]
test_app.py::TestGistAPI::test_caching_mechanism PASSED                                                                                                                                                    [ 53%]
test_app.py::TestGistAPI::test_invalid_username_format PASSED                                                                                                                                              [ 60%]
test_app.py::TestGistAPI::test_real_octocat_gists PASSED                                                                                                                                                   [ 66%]
test_app.py::TestCacheManagement::test_clear_cache PASSED                                                                                                                                                  [ 73%]
test_app.py::TestCacheManagement::test_cache_size_tracking PASSED                                                                                                                                          [ 80%]
test_app.py::TestRootEndpoint::test_root_endpoint PASSED                                                                                                                                                   [ 86%]
test_app.py::TestResponseStructure::test_response_contains_required_fields PASSED                                                                                                                          [ 93%]
test_app.py::TestSecurityHeaders::test_method_not_allowed PASSED                                                                                                                                           [100%]

============================================================================================== 15 passed in 1.49s ===============================================================================================
(venv)


# 7. Run the server
uvicorn app:app --reload --port 8080  or python -m uvicorn app:app --reload --port 8080

# 7. Run requests.http for testing
- Open another terminal and run the requests saved in requests.http file 


#9 stop the Server
   You have to stop the server so you can run the docker or use the docker on a different port
# Find process using port 8080
sudo lsof -i :8080

# Kill the process
sudo kill -9 <PID>

# Or use a different port for Docker
docker run -d -p 8081:8080 --name gist-api github-gist-api


# Build the image
docker build -t github-gist-api .

# List images
docker images | grep github-gist-api

# Run container
docker run -d -p 8080:8080 --name gist-api github-gist-api

# Check if running
docker ps

# View logs
docker logs gist-api

# Follow logs in real-time
docker logs -f gist-api

# 10. Testing Docker Container
# Test health endpoint
docker exec gist-api curl -s http://localhost:8080/health

# Test API endpoint
docker exec gist-api curl -s http://localhost:8080/octocat | python -m json.tool | head -20

# Check container resource usage
docker stats gist-api --no-stream

# Run tests inside container
docker exec gist-api pytest test_app.py -v

# 11. # Stop container
docker stop gist-api

# Remove container
docker rm gist-api

# Remove image
docker rmi github-gist-api

# Complete cleanup
docker stop gist-api && docker rm gist-api && docker rmi github-gist-api

