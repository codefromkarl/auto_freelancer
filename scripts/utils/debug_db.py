
import os
import sys
from pathlib import Path

# Add python_service to sys.path
sys.path.append(str(Path(__file__).parent / "python_service"))

# Setup environment for DB path
os.environ["DATABASE_PATH"] = "python_service/data/freelancer.db"

from database.connection import get_db_session
from database.models import Project

with get_db_session() as db:
    count = db.query(Project).count()
    print(f"Total projects in DB: {count}")
    
    latest = db.query(Project).order_by(Project.created_at.desc()).limit(5).all()
    for p in latest:
        print(f"ID: {p.freelancer_id}, Title: {p.title[:30]}, Score: {p.ai_score}, Status: {p.status}")
