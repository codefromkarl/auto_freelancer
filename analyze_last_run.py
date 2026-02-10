import sys
import os
from datetime import datetime, timedelta

# Add python_service to sys.path
sys.path.insert(0, os.path.join(os.getcwd(), 'python_service'))

from database.connection import get_db_session
from database.models import Project, Bid

def analyze():
    with get_db_session() as db:
        # Check projects updated/scored in the last hour
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        projects = db.query(Project).filter(Project.updated_at >= one_hour_ago, Project.ai_score.isnot(None)).all()
        
        print("Analyzed " + str(len(projects)) + " projects scored in the last hour:\n")
        
        reasons = {
            "low_score": 0,
            "non_usd": 0,
            "already_bid": 0,
            "not_biddable_status": 0,
            "bid_submitted": 0
        }
        
        for p in projects:
            # 1. Check if already bid
            bid = db.query(Bid).filter(Bid.project_freelancer_id == p.freelancer_id).first()
            if bid or p.status == "bid_submitted":
                reasons["bid_submitted"] += 1
                continue
                
            # 2. Check Score (Threshold was 6.5)
            if p.ai_score < 6.5:
                reasons["low_score"] += 1
                continue
                
            # 3. Check Currency (Hard rule in scheduler)
            if (p.currency_code or "USD").upper() != "USD":
                reasons["non_usd"] += 1
                print("Excluded High Score (" + str(p.ai_score) + "): ID " + str(p.freelancer_id) + " is " + str(p.currency_code) + " (Non-USD)")
                continue
            
            # 4. Check Status
            if p.status not in ["open", "active", "open_for_bidding"]:
                reasons["not_biddable_status"] += 1
                continue

        print("\nSummary of exclusions:")
        print("- 评分过低 (< 6.5): " + str(reasons['low_score']))
        print("- 非美元项目 (Non-USD): " + str(reasons['non_usd']))
        print("- 已投过/状态已更新: " + str(reasons['bid_submitted']))
        print("- 状态不可投 (Closed/Frozen): " + str(reasons['not_biddable_status']))

if __name__ == "__main__":
    analyze()