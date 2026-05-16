# GitHub Gist API

A production-ready REST API that fetches public gists from GitHub users with comprehensive error handling, caching, rate limiting awareness, and pagination support.

## Features

- ✅ **Proper error handling** for all GitHub API responses (404, 401, 403, 429, 5xx)
- ✅ **Intelligent response mapping** - Clean DTOs instead of raw GitHub responses
- ✅ **Production-grade caching** - In-memory cache with TTL and size limits
- ✅ **Pagination support** - Navigate through large result sets
- ✅ **Rate limit awareness** - Exposes GitHub rate limits in responses
- ✅ **Comprehensive testing** - Unit, integration, and edge cases
- ✅ **Security hardened** - Non-root user, CORS, trusted hosts
- ✅ **Health checks** - For container orchestration
- ✅ **Retry logic** - Exponential backoff for transient failures

## Prerequisites

- Python 3.11+
- Docker (optional, for containerized deployment)
- GitHub Personal Access Token (optional, for higher rate limits)

## Installation

### Local Development

```bash
# Clone repository
git clone <repository-url>
cd github-gist-api

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Set environment variables (optional)
export GITHUB_TOKEN=your_github_token_here
export CACHE_TTL_SECONDS=300

# Run the server
uvicorn app:app --reload --port 8080