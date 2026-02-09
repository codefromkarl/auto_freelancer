"""
Configuration API endpoints for Scoring Rules and Prompt Templates.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List, Any, Dict
from sqlalchemy.orm import Session
from pydantic import BaseModel
import json

from database.connection import get_db
from database.models import ScoringRule, PromptTemplate
from config import settings
import json

router = APIRouter()

# =============================================================================
# Defaults
# =============================================================================

DEFAULT_SCORING_RULES = [
    {"name": "budget_efficiency", "description": "Project budget vs estimated effort", "weight": 0.15},
    {"name": "competition", "description": "Number of competitors and their quality", "weight": 0.25},
    {"name": "clarity", "description": "Clarity and completeness of description", "weight": 0.25},
    {"name": "customer", "description": "Client history and reputation", "weight": 0.20},
    {"name": "tech_match", "description": "Skills matching score", "weight": 0.10},
    {"name": "risk", "description": "Potential risks (payment, vague specs)", "weight": 0.05},
]

DEFAULT_PROMPT_TEMPLATES = [
    {
        "name": "Standard Analysis",
        "category": "scoring",
        "content": "Analyze the following project description and extract key requirements, skills, and potential risks.\n\nProject:\n{{project_description}}",
        "variables": ["project_description"],
    },
    {
        "name": "Pre-Bid Evaluation (Polling)",
        "category": "scoring",
        "content": (
            "You are a professional freelancer bidding expert.\n\n"
            "## User Profile (Skills & Experience)\n"
            "Core Skills: {{skills}}\n"
            "Relevant Experience: {{experience}}\n\n"
            "## Project to Evaluate\n"
            "Title: {{title}}\n"
            "Budget: {{budget_min}} - {{budget_max}} {{currency}}\n"
            "Description: {{description}}\n\n"
            "## Your Task\n"
            "1. **Rate Match (0-10)**: Evaluate how well this project matches user's skills and experience.\n"
            "2. **Reasoning**: Explain your rating in 2-3 sentences.\n"
            "3. **Bid Strategy**: Suggest a bid amount ({{currency}}) that balances competitiveness and value.\n"
            "4. **Draft Proposal**: Write a professional, concise proposal (2-4 sentences) highlighting relevant skills.\n\n"
            "## Output Format\n"
            "Return valid JSON only:\n"
            "{\n"
            "  \"score\": <number 0-10>,\n"
            "  \"reason\": \"<reasoning>\",\n"
            "  \"suggested_bid\": <number>,\n"
            "  \"proposal_draft\": \"<professional proposal>\"\n"
            "}"
        ),
        "variables": [
            "skills",
            "experience",
            "title",
            "budget_min",
            "budget_max",
            "currency",
            "description",
        ],
    },
    {
        "name": "Professional Bid",
        "category": "proposal",
        "content": "Write a professional bid for this project. Highlight experience with {{skills}}.\n\nProject:\n{{project_description}}",
        "variables": ["project_description", "skills"],
    },
]

# =============================================================================
# Pydantic Models
# =============================================================================

class ScoringRuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    weight: float = 1.0
    is_active: bool = True

class ScoringRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    weight: Optional[float] = None
    is_active: Optional[bool] = None

class PromptTemplateCreate(BaseModel):
    name: str
    category: str
    content: str
    variables: List[str] = []
    is_active: bool = True

class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[List[str]] = None
    is_active: Optional[bool] = None

class APIResponse(BaseModel):
    """Standard API response wrapper."""
    status: str
    data: Any
    message: Optional[str] = None

# =============================================================================
# Scoring Rules Endpoints
# =============================================================================

@router.get("/scoring-rules", response_model=APIResponse)
async def get_scoring_rules(db: Session = Depends(get_db)):
    """Get all scoring rules."""
    try:
        rules = db.query(ScoringRule).all()
        
        if not rules:
            # Seed default rules
            from sqlalchemy.exc import IntegrityError
            for rule_data in DEFAULT_SCORING_RULES:
                rule = ScoringRule(**rule_data)
                db.add(rule)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
            rules = db.query(ScoringRule).all()
            
        return APIResponse(status="success", data=[rule.to_dict() for rule in rules])
    except Exception as e:
        import logging
        logging.error(f"Error fetching scoring rules: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/scoring-rules", response_model=APIResponse)
async def create_scoring_rule(rule: ScoringRuleCreate, db: Session = Depends(get_db)):
    """Create a new scoring rule."""
    existing = db.query(ScoringRule).filter(ScoringRule.name == rule.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Rule with this name already exists")
    
    db_rule = ScoringRule(
        name=rule.name,
        description=rule.description,
        weight=rule.weight,
        is_active=rule.is_active
    )
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return APIResponse(status="success", data=db_rule.to_dict())

@router.put("/scoring-rules/{rule_id}", response_model=APIResponse)
async def update_scoring_rule(rule_id: int, rule_update: ScoringRuleUpdate, db: Session = Depends(get_db)):
    """Update a scoring rule."""
    db_rule = db.query(ScoringRule).filter(ScoringRule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    update_data = rule_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_rule, key, value)
    
    db.commit()
    db.refresh(db_rule)
    return APIResponse(status="success", data=db_rule.to_dict())

@router.delete("/scoring-rules/{rule_id}", response_model=APIResponse)
async def delete_scoring_rule(rule_id: int, db: Session = Depends(get_db)):
    """Delete a scoring rule."""
    db_rule = db.query(ScoringRule).filter(ScoringRule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    db.delete(db_rule)
    db.commit()
    return APIResponse(status="success", data={"message": "Rule deleted"})

# =============================================================================
# Prompt Templates Endpoints
# =============================================================================

@router.get("/prompt-templates", response_model=APIResponse)
async def get_prompt_templates(
    category: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get prompt templates, optionally filtered by category."""
    query = db.query(PromptTemplate)
    if category:
        query = query.filter(PromptTemplate.category == category)
    
    templates = query.all()

    defaults = DEFAULT_PROMPT_TEMPLATES
    if category:
        defaults = [tpl for tpl in DEFAULT_PROMPT_TEMPLATES if tpl["category"] == category]

    if defaults:
        existing_keys = {(t.name, t.category) for t in templates}
        missing_defaults = [
            tpl for tpl in defaults if (tpl["name"], tpl["category"]) not in existing_keys
        ]
        if missing_defaults:
            for tpl_data in missing_defaults:
                tpl = PromptTemplate(
                    name=tpl_data["name"],
                    category=tpl_data["category"],
                    content=tpl_data["content"],
                    variables=json.dumps(tpl_data["variables"]),
                    is_active=True,
                )
                db.add(tpl)
            db.commit()

            # Re-query after seeding missing defaults
            query = db.query(PromptTemplate)
            if category:
                query = query.filter(PromptTemplate.category == category)
            templates = query.all()

    return APIResponse(status="success", data=[t.to_dict() for t in templates])

@router.post("/prompt-templates", response_model=APIResponse)
async def create_prompt_template(template: PromptTemplateCreate, db: Session = Depends(get_db)):
    """Create a new prompt template."""
    db_template = PromptTemplate(
        name=template.name,
        category=template.category,
        content=template.content,
        variables=json.dumps(template.variables),
        is_active=template.is_active
    )
    db.add(db_template)
    db.commit()
    db.refresh(db_template)
    return APIResponse(status="success", data=db_template.to_dict())

@router.put("/prompt-templates/{template_id}", response_model=APIResponse)
async def update_prompt_template(
    template_id: int, 
    template_update: PromptTemplateUpdate, 
    db: Session = Depends(get_db)
):
    """Update a prompt template."""
    db_template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not db_template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    update_data = template_update.dict(exclude_unset=True)
    
    if "variables" in update_data:
        update_data["variables"] = json.dumps(update_data["variables"])
        
    for key, value in update_data.items():
        setattr(db_template, key, value)
    
    db.commit()
    db.refresh(db_template)
    return APIResponse(status="success", data=db_template.to_dict())

@router.delete("/prompt-templates/{template_id}", response_model=APIResponse)
async def delete_prompt_template(template_id: int, db: Session = Depends(get_db)):
    """Delete a prompt template."""
    db_template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not db_template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    db.delete(db_template)
    db.commit()
    return APIResponse(status="success", data={"message": "Template deleted"})
