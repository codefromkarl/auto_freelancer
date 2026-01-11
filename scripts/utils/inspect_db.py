from scripts.manual_pipeline import common
from database.models import Project

settings = common.get_settings()
print(f"DB Path: {settings.DATABASE_PATH}")

with common.get_db_context() as db:
    projects = db.query(Project).all()
    print(f"Total projects: {len(projects)}")
    
    for p in projects:
        print(f"ID: {p.freelancer_id}, Title: {p.title[:30]}, Score: {p.ai_score}, Created: {p.created_at}")
