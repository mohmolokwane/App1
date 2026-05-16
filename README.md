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
10.[Performance Benchmarks](#performance-benchmarks)
11.[Security Features](#security-features)
12.[Quick Reference](#quick-reference)


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

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Upgrade pip
pip install --upgrade pip

# 4. Install dependencies
pip install -r requirements.txt

# 5. Set up environment variables (optional)
export GITHUB_TOKEN=your_github_token_here  # Optional: for higher rate limits
export CACHE_TTL_SECONDS=300  # Optional: cache duration in seconds
export DEFAULT_PAGE_SIZE=30  # Optional: default items per page

# 6. Run the server
uvicorn app:app --reload --port 8080

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

# Stop uvicorn if running
pkill -f uvicorn

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

