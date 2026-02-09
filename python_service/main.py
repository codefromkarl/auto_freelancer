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
from database.connection import init_db, get_db_session, verify_api_key
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


# Statistics endpoint
@app.get("/api/v1/stats")
async def get_stats(api_key: str = Depends(verify_api_key)):
    """Get service statistics."""
    from database.models import Project, Bid, Milestone
    from sqlalchemy import func
    from datetime import datetime, timedelta

    with get_db_session() as db:
        # Core counts
        project_count = db.query(Project).count()
        bid_count = db.query(Bid).count()
        milestone_count = db.query(Milestone).count()
        
        # Today's new projects
        yesterday = datetime.utcnow() - timedelta(days=1)
        today_new = db.query(Project).filter(Project.created_at >= yesterday).count()
        
        # Average score
        avg_score = db.query(func.avg(Project.ai_score)).filter(Project.ai_score.isnot(None)).scalar() or 0
        
        # Pending bids (assuming status is 'active')
        pending_bids = db.query(Bid).filter(Bid.status == 'active').count()

        # Score distribution for charts
        # 0-2, 2-4, 4-6, 6-8, 8-10
        score_dist = []
        for i in range(0, 10, 2):
            if i == 8:
                count = db.query(Project).filter(Project.ai_score >= i, Project.ai_score <= 10.0).count()
            else:
                count = db.query(Project).filter(Project.ai_score >= i, Project.ai_score < i + 2).count()
            score_dist.append({"range": f"{i}-{i+2}", "count": count})
        
        # Budget distribution
        # <100, 100-500, 500-1000, >1000 (USD)
        budget_dist = [
            {"name": "< $100", "value": db.query(Project).filter(Project.budget_maximum < 100).count()},
            {"name": "$100 - $500", "value": db.query(Project).filter(Project.budget_maximum >= 100, Project.budget_maximum < 500).count()},
            {"name": "$500 - $1000", "value": db.query(Project).filter(Project.budget_maximum >= 500, Project.budget_maximum < 1000).count()},
            {"name": "> $1000", "value": db.query(Project).filter(Project.budget_maximum >= 1000).count()},
        ]

    return {
        "status": "success",
        "data": {
            "total_projects": project_count,
            "today_new": today_new,
            "avg_score": float(avg_score),
            "pending_bids": pending_bids,
            "total_bids": bid_count,
            "total_milestones": milestone_count,
            "score_distribution": score_dist,
            "budget_distribution": budget_dist,
            "version": settings.APP_VERSION
        }
    }


# Import routers
from api import projects, bids, milestones, messages, ai_replies, kickoff, client_risk, configuration, proposals

# Include routers
app.include_router(
    configuration.router,
    prefix=settings.API_V1_PREFIX,
    tags=["Configuration"]
)

# Print all routes for debugging
@app.on_event("startup")
async def print_routes():
    import logging
    for route in app.routes:
        logging.info(f"Route: {route.path} [{getattr(route, 'methods', '')}]")
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
    proposals.router,
    prefix=f"{settings.API_V1_PREFIX}/proposals",
    tags=["Proposals"]
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
    prefix=f"{settings.API_V1_PREFIX}/ai-replies",
    tags=["AI Replies"]
)
app.include_router(
    kickoff.router,
    prefix=f"{settings.API_V1_PREFIX}/kickoff",
    tags=["Kick-off"]
)
app.include_router(
    client_risk.router,
    prefix=f"{settings.API_V1_PREFIX}/risk",
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
