# AI Syndicate - SyndicateClaw Repository

## Overview
SyndicateClaw is the web frontend for the AI Syndicate ecosystem, providing a user-facing interface for AI agent interactions and services.

## Repository Structure
- `src/syndicateclaw/` - Application source code
- `src/syndicateclaw/api/` - API handlers and middleware
- `tests/` - Test suite

## Key Features
- Modern Python/FastAPI backend
- Agent interaction interface
- Integration with backend services

## Agent Skills Documentation
This repository documents the frontend agent skills and user interface patterns used across the syndicate ecosystem.

## API Middleware
The repository includes middleware at `src/syndicateclaw/api/middleware.py` for handling:
- Request/response processing
- Agent header management
- API routing and authentication

## Markdown for Agents
The frontend website (syndicateclaw-website) handles Markdown for Agents support. When requests include `Accept: text/markdown`, the website returns Markdown-formatted responses.

## Related Repositories
- aisyndicate: Core agent orchestration services
- syndicatecode-website: Developer documentation
- syndicategate: API gateway with agent headers
