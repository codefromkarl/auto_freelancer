"""
SQLAlchemy database models for Freelancer automation.
"""
from sqlalchemy import Column, Integer, String, Text, DECIMAL, Boolean, DateTime, ForeignKey, Index, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from .connection import Base


class Project(Base):
    """Projects table for storing fetched project data."""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    freelancer_id = Column(Integer, unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    preview_description = Column(Text)
    budget_minimum = Column(DECIMAL(10, 2))
    budget_maximum = Column(DECIMAL(10, 2))
    currency_code = Column(String(3), default="USD")
    submitdate = Column(String(50), index=True)
    status = Column(String(20), default="open", index=True)
    type_id = Column(Integer)
    skills = Column(Text)  # JSON array of skill IDs
    owner_id = Column(Integer)
    country = Column(String(100))
    deadline = Column(String(50))
    watched = Column(Boolean, default=False)

    # 详细API返回的额外字段（用于评分）
    bid_stats = Column(Text)  # JSON: {bid_count: N, ...}
    owner_info = Column(Text)  # JSON: {online_status, jobs_posted, rating, ...}

    ai_score = Column(Float)  # AI analysis score (0-1.9)
    ai_reason = Column(Text)  # AI analysis reason
    ai_proposal_draft = Column(Text)  # AI generated proposal
    suggested_bid = Column(DECIMAL(10, 2))  # AI suggested bid amount in USD
    estimated_hours = Column(Integer)  # AI estimated work hours
    hourly_rate = Column(Float)  # AI calculated hourly rate (USD/h)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    bids = relationship("Bid", back_populates="project", foreign_keys="[Bid.project_id]")
    milestones = relationship("Milestone", back_populates="project", foreign_keys="[Milestone.project_id]")

    def to_dict(self):
        """Convert model to dictionary."""
        import json
        return {
            "id": self.freelancer_id,
            "title": self.title,
            "description": self.description,
            "preview_description": self.preview_description,
            "budget_minimum": float(self.budget_minimum) if self.budget_minimum else None,
            "budget_maximum": float(self.budget_maximum) if self.budget_maximum else None,
            "currency_code": self.currency_code,
            "submitdate": self.submitdate,
            "status": self.status,
            "skills": self.skills,
            "owner_id": self.owner_id,
            "deadline": self.deadline,
            "bid_stats": json.loads(self.bid_stats) if self.bid_stats else None,
            "owner_info": json.loads(self.owner_info) if self.owner_info else None,
            "ai_score": self.ai_score,
            "ai_reason": self.ai_reason,
            "ai_proposal_draft": self.ai_proposal_draft,
            "estimated_hours": self.estimated_hours,
            "hourly_rate": self.hourly_rate,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Bid(Base):
    """Bids table for tracking bid history."""
    __tablename__ = "bids"

    id = Column(Integer, primary_key=True, autoincrement=True)
    freelancer_bid_id = Column(Integer, unique=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    project_freelancer_id = Column(Integer, ForeignKey("projects.freelancer_id"), nullable=False)
    bidder_id = Column(Integer, nullable=False)
    amount = Column(DECIMAL(10, 2))
    period = Column(Integer)  # Duration in days
    description = Column(Text)
    reaward_count = Column(Integer, default=0)
    status = Column(String(20), default="active", index=True)  # active, withdrawn, completed
    submitdate = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="bids", foreign_keys=[project_id])

    Index("idx_bids_project", "project_id")
    Index("idx_bids_status", "status")

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": self.freelancer_bid_id,
            "project_id": self.project_freelancer_id,
            "bidder_id": self.bidder_id,
            "amount": float(self.amount) if self.amount else None,
            "period": self.period,
            "description": self.description,
            "status": self.status,
            "submitdate": self.submitdate,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Milestone(Base):
    """Milestones table for payment tracking."""
    __tablename__ = "milestones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    freelancer_milestone_id = Column(Integer, unique=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    project_freelancer_id = Column(Integer, ForeignKey("projects.freelancer_id"), nullable=False)
    amount = Column(DECIMAL(10, 2))
    description = Column(Text)
    due_date = Column(String(50))
    status = Column(String(20))  # pending, created, accepted, paid, cancelled
    bid_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="milestones", foreign_keys=[project_id])

    Index("idx_milestones_project", "project_id")
    Index("idx_milestones_status", "status")

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": self.freelancer_milestone_id,
            "project_id": self.project_freelancer_id,
            "amount": float(self.amount) if self.amount else None,
            "description": self.description,
            "due_date": self.due_date,
            "status": self.status,
            "bid_id": self.bid_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MessageThread(Base):
    """Message threads table."""
    __tablename__ = "message_threads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    freelancer_thread_id = Column(Integer, unique=True, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True)
    project_freelancer_id = Column(Integer, ForeignKey("projects.freelancer_id"))
    participants = Column(Text)  # JSON array of user IDs
    last_message_time = Column(String(50))
    last_message_preview = Column(Text)
    unread_count = Column(Integer, default=0, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    Index("idx_threads_project", "project_id")
    Index("idx_threads_unread", "unread_count")

    # 关联：AI 生成的回复备选项（按线程维度存储）
    ai_reply_options = relationship(
        "AIReplyOption",
        back_populates="thread",
        primaryjoin="MessageThread.freelancer_thread_id==AIReplyOption.thread_id",
    )


class Message(Base):
    """Messages table for message history."""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    freelancer_message_id = Column(Integer, unique=True, nullable=False)
    thread_id = Column(Integer, ForeignKey("message_threads.freelancer_thread_id"), nullable=False, index=True)
    user_id = Column(Integer)
    username = Column(String(100))
    message = Column(Text)
    attachment_url = Column(Text)
    attachment_name = Column(String(500))
    send_time = Column(String(50), index=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    Index("idx_messages_thread", "thread_id")
    Index("idx_messages_time", "send_time")

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": self.freelancer_message_id,
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "username": self.username,
            "message": self.message,
            "attachment_url": self.attachment_url,
            "attachment_name": self.attachment_name,
            "send_time": self.send_time,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AIReplyOption(Base):
    """
    AI 生成的回复备选项表。

    设计说明：
    - 以 Freelancer 的 `thread_id` 为主索引，便于按对话线程检索
    - 存储脱敏后的上下文快照（context_messages_masked），用于审计与复盘
    """

    __tablename__ = "ai_reply_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(
        Integer,
        ForeignKey("message_threads.freelancer_thread_id"),
        nullable=False,
        index=True,
    )
    tone = Column(String(20), nullable=False)  # professional / enthusiastic / concise
    text = Column(Text, nullable=False)

    # 记录 LLM 侧元数据，便于排查不同模型输出差异
    provider = Column(String(50), default="openai")
    model = Column(String(100))

    # 保存脱敏后的上下文消息（JSON-like 字符串）
    context_messages_masked = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    Index("idx_ai_reply_thread_time", "thread_id", "created_at")

    # 关联到线程（thread_id 指向 message_threads.freelancer_thread_id）
    thread = relationship(
        "MessageThread",
        back_populates="ai_reply_options",
        foreign_keys=[thread_id],
    )


class AuditLog(Base):
    """Audit logs table for tracking API calls."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String(50), nullable=False)
    entity_type = Column(String(50))  # project, bid, milestone, message
    entity_id = Column(Integer)
    request_data = Column(Text)  # JSON
    response_data = Column(Text)  # JSON
    status = Column(String(20))  # success, error
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    Index("idx_audit_entity", "entity_type", "entity_id")
    Index("idx_audit_time", "created_at")

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# Client Risk Management Models (方向四：客户尽职调查与风控盾)
# =============================================================================

class Client(Base):
    """
    Clients table for storing Freelancer employer information.

    Stores client (employer) metadata for risk assessment and filtering.
    Separate from Project.owner_info to enable client-level analysis across multiple projects.
    """
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    freelancer_user_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(100))

    # Payment & verification status (hard rule filters)
    payment_verified = Column(Boolean, default=False, index=True)
    deposit_made = Column(Boolean, default=False, index=True)
    verified = Column(Boolean, default=False)  # General account verification

    # Location info (for country denylist)
    country = Column(String(3))  # ISO 3166-1 alpha-2 country code
    country_name = Column(String(100))

    # Activity metrics
    jobs_posted = Column(Integer, default=0)
    jobs_hired = Column(Integer, default=0)
    hire_rate = Column(Float)  # Calculated: jobs_hired / jobs_posted

    # Rating info
    rating = Column(Float)  # Average rating (0-5)
    review_count = Column(Integer, default=0)

    # Raw API data (for audit and fallback)
    profile_raw_json = Column(Text)  # Full JSON response from getUser API

    # Tracking
    last_seen_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    feature_snapshots = relationship("ClientFeatureSnapshot", back_populates="client", order_by="desc(ClientFeatureSnapshot.collected_at)")
    risk_assessments = relationship("ClientRiskAssessment", back_populates="client", order_by="desc(ClientRiskAssessment.created_at)")

    Index("idx_clients_user_id", "freelancer_user_id")
    Index("idx_clients_country", "country")
    Index("idx_clients_payment", "payment_verified")

    def to_dict(self):
        """Convert model to dictionary."""
        import json
        return {
            "id": self.id,
            "freelancer_user_id": self.freelancer_user_id,
            "username": self.username,
            "payment_verified": self.payment_verified,
            "deposit_made": self.deposit_made,
            "verified": self.verified,
            "country": self.country,
            "country_name": self.country_name,
            "jobs_posted": self.jobs_posted,
            "jobs_hired": self.jobs_hired,
            "hire_rate": self.hire_rate,
            "rating": self.rating,
            "review_count": self.review_count,
            "profile_raw_json": json.loads(self.profile_raw_json) if self.profile_raw_json else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ClientFeatureSnapshot(Base):
    """
    Client feature snapshots table.

    Stores versioned snapshots of client features for historical analysis and policy version comparison.
    Enables tracking client reputation changes over time.
    """
    __tablename__ = "client_feature_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    # Source of the data
    source = Column(String(20), default="api")  # "api" or "scrape"

    # Feature JSON (structured feature set)
    features_json = Column(Text, nullable=False)  # JSON: {
        #   "jobs_posted": 10,
        #   "jobs_hired": 7,
        #   "hire_rate": 0.7,
        #   "rating": 4.5,
        #   "review_count": 12,
        #   "avg_bid_count": 8,
        #   "dispute_count": 0,
        #   ...
        # }

    # Raw reviews data (if available)
    reviews_raw_json = Column(Text)  # JSON array of review objects

    # Metadata
    collected_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    client = relationship("Client", back_populates="feature_snapshots")

    Index("idx_snapshots_client", "client_id")
    Index("idx_snapshots_collected", "collected_at")

    def to_dict(self):
        """Convert model to dictionary."""
        import json
        return {
            "id": self.id,
            "client_id": self.client_id,
            "source": self.source,
            "features": json.loads(self.features_json) if self.features_json else None,
            "reviews": json.loads(self.reviews_raw_json) if self.reviews_raw_json else None,
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
        }


class ClientRiskAssessment(Base):
    """
    Client risk assessments table.

    Stores risk scores and analysis results from both hard rules and LLM soft analysis.
    One project can trigger a new assessment; assessments are versioned for comparison.
    """
    __tablename__ = "client_risk_assessments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)  # Null for periodic reassessment

    # Risk score (0-100, higher = more risky)
    risk_score = Column(Integer, nullable=False, index=True)

    # Hard rule flags (list of triggered rules)
    hard_flags_json = Column(Text)  # JSON array: [
        #   "PAYMENT_NOT_VERIFIED",
        #   "DEPOSIT_NOT_MADE",
        #   "COUNTRY_BLOCKED",
        #   "ZERO_REVIEWS",
        #   "LOW_HIRE_RATE",
        # ]
    hard_gate_passed = Column(Boolean, default=False, index=True)  # Whether the client passed hard gate check

    # LLM soft analysis results
    llm_summary = Column(Text)  # Natural language summary
    llm_evidence_json = Column(Text)  # JSON: {
        #   "negative_review_frequency": 0.15,
        #   "common_complaints": ["slow payment", "vague requirements"],
        #   "dispute_signals": 0,
        #   "hire_rate_assessment": "high",
        #   "risk_delta": -10,  # Negative means lower risk
        # }

    # Combined reasoning
    reasons_json = Column(Text)  # JSON array of human-readable reasons

    # Model metadata
    risk_policy_version = Column(String(20), default="v1")  # For strategy versioning
    model_provider = Column(String(50), default="openai")
    model_name = Column(String(100))

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    client = relationship("Client", back_populates="risk_assessments")

    Index("idx_risk_client", "client_id")
    Index("idx_risk_project", "project_id")
    Index("idx_risk_score", "risk_score")
    Index("idx_risk_gate", "hard_gate_passed")

    def to_dict(self):
        """Convert model to dictionary."""
        import json
        return {
            "id": self.id,
            "client_id": self.client_id,
            "project_id": self.project_id,
            "risk_score": self.risk_score,
            "hard_flags": json.loads(self.hard_flags_json) if self.hard_flags_json else [],
            "hard_gate_passed": self.hard_gate_passed,
            "llm_summary": self.llm_summary,
            "llm_evidence": json.loads(self.llm_evidence_json) if self.llm_evidence_json else None,
            "reasons": json.loads(self.reasons_json) if self.reasons_json else [],
            "risk_policy_version": self.risk_policy_version,
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# Project Kick-off Automation Models (方向六：中标后的"瞬间启动"工作流)
# =============================================================================

class ProjectKickoff(Base):
    """
    Project kick-off records table.

    Tracks automatic project initialization after winning a bid.
    Stores repository creation, collaboration space setup, and notification status.
    """
    __tablename__ = "project_kickoffs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    project_freelancer_id = Column(Integer, ForeignKey("projects.freelancer_id"), nullable=False)
    bid_id = Column(Integer, ForeignKey("bids.id"), nullable=False)  # Winning bid reference

    # Repository info
    repo_provider = Column(String(20), default="github")  # github, gitlab
    repo_name = Column(String(200))
    repo_url = Column(String(500))
    repo_created_at = Column(DateTime)
    repo_status = Column(String(20), default="pending")  # pending, created, failed

    # Collaboration space info
    collab_provider = Column(String(20))  # notion, trello, jira
    collab_space_url = Column(String(500))
    collab_space_id = Column(String(200))
    collab_created_at = Column(DateTime)
    collab_status = Column(String(20), default="pending")  # pending, created, failed

    # Template used for scaffolding
    template_type = Column(String(50))  # web_scraping, api_development, data_analysis, automation, custom

    # Notifications
    notification_sent = Column(Boolean, default=False)  # Telegram notification
    notification_sent_at = Column(DateTime)
    client_email_sent = Column(Boolean, default=False)  # Client welcome email
    client_email_sent_at = Column(DateTime)
    client_email_error = Column(Text)

    # Metadata
    kickoff_summary = Column(Text)  # JSON summary of what was initialized
    error_message = Column(Text)  # Any errors during kick-off

    # Timestamps
    triggered_at = Column(DateTime, default=datetime.utcnow, index=True)  # When kick-off was triggered
    completed_at = Column(DateTime)  # When kick-off completed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", foreign_keys=[project_id])
    bid = relationship("Bid", foreign_keys=[bid_id])

    Index("idx_kickoffs_project", "project_id")
    Index("idx_kickoffs_bid", "bid_id")
    Index("idx_kickoffs_triggered", "triggered_at")
    Index("idx_kickoffs_status", "repo_status")

    def to_dict(self):
        """Convert model to dictionary."""
        import json
        return {
            "id": self.id,
            "project_id": self.project_freelancer_id,
            "bid_id": self.bid_id,
            "repo_provider": self.repo_provider,
            "repo_name": self.repo_name,
            "repo_url": self.repo_url,
            "repo_status": self.repo_status,
            "repo_created_at": self.repo_created_at.isoformat() if self.repo_created_at else None,
            "collab_provider": self.collab_provider,
            "collab_space_url": self.collab_space_url,
            "collab_space_id": self.collab_space_id,
            "collab_status": self.collab_status,
            "collab_created_at": self.collab_created_at.isoformat() if self.collab_created_at else None,
            "template_type": self.template_type,
            "notification_sent": self.notification_sent,
            "notification_sent_at": self.notification_sent_at.isoformat() if self.notification_sent_at else None,
            "client_email_sent": self.client_email_sent,
            "client_email_sent_at": self.client_email_sent_at.isoformat() if self.client_email_sent_at else None,
            "kickoff_summary": json.loads(self.kickoff_summary) if self.kickoff_summary else None,
            "error_message": self.error_message,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
