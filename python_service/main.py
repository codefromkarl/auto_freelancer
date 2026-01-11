"""
FastAPI main application for Freelancer automation.
"""
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import sys
from pathlib import Path

from config import settings
from database.connection import init_db, get_db_session
from services.freelancer_client import get_freelancer_client, FreelancerAPIError
from middleware.error_handler import (
    freelancer_exception_handler,
    general_exception_handler
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(settings.LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    init_db()
    logger.info("Database initialized")

    yield

    # Shutdown
    logger.info("Shutting down application")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register exception handlers
app.add_exception_handler(FreelancerAPIError, freelancer_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)


# API Key authentication dependency
async def verify_api_key(request: Request):
    """Verify API key from request header."""
    api_key = request.headers.get("X-API-Key")

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key"
        )

    if api_key != settings.PYTHON_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key"
        )

    return api_key


# Statistics endpoint
@app.get("/api/v1/stats")
async def get_stats(api_key: str = Depends(verify_api_key)):
    """Get service statistics."""
    from database.models import Project, Bid, Milestone

    with get_db_session() as db:
        project_count = db.query(Project).count()
        bid_count = db.query(Bid).count()
        milestone_count = db.query(Milestone).count()

    return {
        "status": "success",
        "data": {
            "total_projects": project_count,
            "total_bids": bid_count,
            "total_milestones": milestone_count,
            "version": settings.APP_VERSION
        }
    }


# Import routers
from api import projects, bids, milestones, messages, ai_replies, kickoff, client_risk

# Include routers
app.include_router(
    projects.router,
    prefix=f"{settings.API_V1_PREFIX}/projects",
    tags=["Projects"]
)
app.include_router(
    bids.router,
    prefix=f"{settings.API_V1_PREFIX}/bids",
    tags=["Bids"]
)
app.include_router(
    milestones.router,
    prefix=f"{settings.API_V1_PREFIX}/milestones",
    tags=["Milestones"]
)
app.include_router(
    messages.router,
    prefix=f"{settings.API_V1_PREFIX}/messages",
    tags=["Messages"]
)
app.include_router(
    ai_replies.router,
    prefix=f"{settings.API_V1_PREFIX}/ai",
    tags=["AI"]
)
app.include_router(
    kickoff.router,
    prefix=f"{settings.API_V1_PREFIX}/kickoff",
    tags=["Kickoff"]
)
app.include_router(
    client_risk.router,
    prefix=f"{settings.API_V1_PREFIX}/client-risk",
    tags=["Client Risk"]
)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for Docker."""
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "service": settings.APP_NAME
    }


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        log_level=settings.LOG_LEVEL.lower()
    )
