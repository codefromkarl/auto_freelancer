
import sys
import os
import logging

# Add python_service to path
sys.path.append(os.path.abspath("python_service"))

from services.project_scorer import ProjectScorer, ScoreBreakdown
from config import settings

# Mock project data
projects = [
    {
        "id": 40136975,
        "title": "Apple App Store Launch Assistance",
        "description": "Need help launching app. Requirements: A, B, C.",
        "budget": {"minimum": 250, "maximum": 750},
        "currency_code": "EUR",
        "bid_stats": {"bid_count": 12},
        "owner_info": {"payment_verified": True, "jobs_posted": 10, "jobs_hired": 5, "rating": 5.0}
    },
    {
        "id": 40121085,
        "title": "Python Script for GSTN to TallyPrime Conversion",
        "description": "Python script needed. GSTN TallyPrime.",
        "budget": {"minimum": 1500, "maximum": 12500},
        "currency_code": "INR",
        "bid_stats": {"bid_count": 15}, # Moderate
        "owner_info": {"payment_verified": True}
    },
    {
        "id": 40136175,
        "title": "Build AI Contact Search Platform",
        "description": "Build AI platform. Python, ML, NLP. Deliverables: Source code.",
        "budget": {"minimum": 75000, "maximum": 150000},
        "currency_code": "INR",
        "bid_stats": {"bid_count": 10},
        "owner_info": {"payment_verified": True}
    }
]

scorer = ProjectScorer()

print(f"{'ID':<10} {'Title':<40} {'Est.Hrs':<8} {'USD/Hr':<8} {'Bud.Score':<10} {'Total':<6} {'Reason'}")
print("-" * 120)

for p in projects:
    score_res = scorer.score_project(p)
    bd = score_res.score_breakdown
    print(f"{p['id']:<10} {p['title'][:38]:<40} {bd.estimated_hours:<8} {bd.hourly_rate:<8.2f} {bd.budget_efficiency_score:<10.2f} {score_res.ai_score:<6.2f} {score_res.ai_reason}")

