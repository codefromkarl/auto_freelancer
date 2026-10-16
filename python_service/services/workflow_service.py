"""Persistent candidate decisions, clarification context and measured workflow events."""
import json
import sqlite3
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import object_session

from database.models import Project, CandidateWorkflow, WorkflowEvent, WorkflowRun, BidSubmission, Bid
from services.project_service import project_material_fields
from services.scoring_policy import digest, object_value, score_is_current, policy_signature

CURRENT_RUN = ContextVar("workflow_run_id", default=None)
STATES = {"needs_evaluation", "needs_clarification", "ready", "awaiting_approval", "awaiting_submission",
          "deferred", "rejected", "submitted", "outcome_unknown"}


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def material_hash(project):
    return digest(project_material_fields(project))


def event(db, stage, outcome, *, project_id=None, reason=None, count=1,
          duration_ms=None, details=None, key=None):
    if key and (any(isinstance(item, WorkflowEvent) and item.event_key == key for item in db.new)
                or db.query(WorkflowEvent.id).filter_by(event_key=key).first()):
        return
    db.add(WorkflowEvent(run_id=CURRENT_RUN.get(), project_freelancer_id=project_id,
        stage=stage, outcome=outcome, reason_code=reason, count=count,
        duration_ms=duration_ms, details=json.dumps(details, ensure_ascii=False) if details else None,
        event_key=key))


def transition(db, row, state, code, reason, **fields):
    if state not in STATES:
        raise ValueError("Unknown candidate state")
    changed = (row.state, row.reason_code, row.reason) != (state, code, reason)
    changed |= any(getattr(row, key) != value for key, value in fields.items())
    if changed:
        row.state, row.reason_code, row.reason = state, code, reason
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = now()
        event(db, "queue", state, project_id=row.project_freelancer_id, reason=code)
    return row


def ensure(db, project):
    row = db.query(CandidateWorkflow).filter_by(project_freelancer_id=project.freelancer_id).first()
    version = material_hash(project)
    if row is None:
        row = CandidateWorkflow(project_freelancer_id=project.freelancer_id,
            material_hash=version, questions="[]", answers="[]",
            state="needs_evaluation", reason_code="new_project", reason="等待范围与能力评估")
        db.add(row)
        db.flush()
        event(db, "queue", "needs_evaluation", project_id=project.freelancer_id, reason="new_project")
    elif row.material_hash != version:
        row.material_hash = version
        row.questions, row.answers, row.approval_id = "[]", "[]", None
        if row.held_by != "operator" and row.resume_condition != "manual" and row.state not in {"submitted", "outcome_unknown"}:
            transition(db, row, "needs_evaluation", "scope_changed", "需求或预算已变化，等待重新评估",
                       held_by=None, resume_condition=None, resume_at=None)
        else:
            row.updated_at = now()
    return row


def clarification_context(project):
    if not isinstance(project, Project):
        return []
    db = object_session(project)
    if db is None:
        return []
    row = db.query(CandidateWorkflow).filter_by(project_freelancer_id=project.freelancer_id).first()
    if row is None or row.material_hash != material_hash(project):
        return []
    return object_value(row.answers) or []


def context_hash(project):
    return digest(clarification_context(project))


def held(row):
    return row is not None and row.state in {"needs_clarification", "deferred", "rejected", "submitted", "outcome_unknown"}


def evaluation_allowed(db, project):
    row = ensure(db, project)
    if row.state in {'deferred', 'rejected'} and row.resume_condition == 'scope_or_policy_changed':
        from database.models import WorkflowEvent
        last = db.query(WorkflowEvent).filter_by(project_freelancer_id=project.freelancer_id,
            stage='evaluation', outcome='deferred').order_by(WorkflowEvent.id.desc()).first()
        details = object_value(last.details) if last else {}
        if (details and details.get('material_hash') == material_hash(project)
                and details.get('policy_hash') == policy_signature(db)):
            return False
        transition(db, row, 'needs_evaluation', 'evaluation_context_changed', '需求或策略已变化，重新评估',
                   held_by=None, resume_condition=None)
    if row.state in {"needs_clarification", "awaiting_approval", "awaiting_submission", "submitted", "outcome_unknown"}:
        return False
    if row.held_by == "operator" or row.resume_condition == "manual":
        if row.resume_condition == "time" and row.resume_at and row.resume_at <= now():
            transition(db, row, "needs_evaluation", "defer_elapsed", "暂缓时间已到，重新评估",
                       held_by=None, resume_condition=None, resume_at=None)
        else:
            return False
    return True


def scope_questions(project):
    if not isinstance(project, Project):
        return []
    db = object_session(project)
    if db is None:
        return []
    row = db.query(CandidateWorkflow).filter_by(project_freelancer_id=project.freelancer_id).first()
    return (object_value(row.questions) or []) if row else []


def defer_evaluation(db, project, signature, reason):
    row = ensure(db, project)
    if row.held_by == 'operator' or row.resume_condition == 'manual':
        return
    invalidate_score(project)
    transition(db, row, 'deferred', 'invalid_model_terms', reason,
               held_by='system', resume_condition='scope_or_policy_changed')
    event(db, 'evaluation', 'deferred', project_id=project.freelancer_id, reason='invalid_model_terms',
          details={'policy_hash':signature, 'material_hash':material_hash(project)})


def invalidate_score(project):
    for name in ("ai_score", "ai_reason", "score_metadata", "scored_at", "estimated_hours",
                 "hourly_rate", "suggested_bid", "ai_proposal_draft"):
        setattr(project, name, None)


def apply_score(db, project):
    row = ensure(db, project)
    if row.held_by == "operator" or row.resume_condition == "manual" or row.state in {"submitted", "outcome_unknown"}:
        return row
    metadata = object_value(project.score_metadata) or {}
    if metadata.get('recommendation') == 'reject':
        reason = project.ai_reason or '模型建议排除该任务'
        transition(db, row, 'rejected', 'model_rejected', reason,
                   held_by='system', resume_condition='scope_or_policy_changed')
        event(db, 'evaluation', 'deferred', project_id=project.freelancer_id, reason='model_rejected',
              details={'policy_hash':policy_signature(db), 'material_hash':material_hash(project)})
        return row
    questions = metadata.get("clarification_questions") or []
    if questions:
        structured = [{"id": digest(question)[:16], "question": question} for question in questions]
        return transition(db, row, "needs_clarification", "scope_unknown",
            "关键范围尚未明确，请先补充信息再报价", questions=json.dumps(structured, ensure_ascii=False),
            held_by="system", resume_condition="answers", resume_at=None)
    transition(db, row, "needs_evaluation", "scored", "已完成评分，等待候选可行性检查",
               questions="[]", held_by=None, resume_condition=None, resume_at=None)
    from config import settings
    return refresh_readiness(db, project, settings.BID_MIN_AUTO_SCORE if settings.BID_APPROVAL_MODE=='automatic' else 7.0)


def classify_terms_error(message):
    if "净时薪" in message:
        return "low_net_hourly"
    if "工时超过" in message:
        return "scope_too_large"
    if "付款验证" in message:
        return "payment_unverified"
    if "汇率" in message:
        return "currency_unknown"
    return "terms_invalid"


def refresh_readiness(db, project, threshold, signature=None):
    row = ensure(db, project)
    if row.state in {'deferred','rejected'} and row.resume_condition == 'scope_or_policy_changed' and not evaluation_allowed(db,project):
        return row
    if row.held_by == "operator" or row.resume_condition == "manual":
        if row.resume_condition == "time" and row.resume_at and row.resume_at <= now():
            transition(db, row, "needs_evaluation", "defer_elapsed", "暂缓时间已到，重新检查",
                       held_by=None, resume_condition=None, resume_at=None)
        else:
            return row
    if row.state in {"submitted", "outcome_unknown", "awaiting_approval", "awaiting_submission"}:
        return row
    if str(project.status or "").lower() not in {"open", "active", "open_for_bidding"}:
        return transition(db, row, "deferred", "not_biddable", "项目当前状态不可投标",
                          held_by="system", resume_condition="remote_status_changed")
    if not score_is_current(project, signature or policy_signature(db)):
        if row.state != "needs_clarification":
            transition(db, row, "needs_evaluation", "score_stale", "等待有效的当前版本评分")
        return row
    metadata = object_value(project.score_metadata)
    if metadata.get("clarification_questions"):
        return apply_score(db, project)
    if project.ai_score < threshold:
        return transition(db, row, "deferred", "score_below_threshold", "当前评分低于候选阈值",
                          held_by="system", resume_condition="score_changed")
    if metadata.get("candidate_blocked"):
        return transition(db, row, "deferred", "preparation_failed", "本次准备失败，等待重评或人工恢复",
                          held_by="system", resume_condition="score_changed")
    from services.bid_service import _resolve_submission_amount
    from services.approved_bids import validate_terms, risk_review
    import math
    try:
        hours = project.estimated_hours
        if not hours or project.suggested_bid is None:
            raise ValueError("报价或估算工时未知")
        native = _resolve_submission_amount(project, float(project.suggested_bid), "USD")
        from config import settings
        if settings.BID_APPROVAL_MODE == 'automatic':
            from services.automatic_bid_policy import resolve_quote
            native = resolve_quote(project, native, {'status': 'missing'})
        validate_terms(project, native, min(30, max(2, math.ceil(hours / 6))))
        unknown, _ = risk_review(project)
        if (settings.BID_APPROVAL_MODE == 'automatic' and unknown
                and settings.BID_AUTO_REQUIRE_VERIFIED_CLIENT_PAYMENT):
            return transition(db, row, 'deferred', 'payment_unknown', '客户付款验证未知，自动暂缓',
                              held_by='system', resume_condition='remote_data_changed')
        if settings.BID_APPROVAL_MODE == 'automatic':
            from services.automatic_bid_policy import validate_local_candidate
            validate_local_candidate(project, native, min(30, max(2, math.ceil(hours / 6))))
    except (ValueError, TypeError, OverflowError) as exc:
        return transition(db, row, "deferred", classify_terms_error(str(exc)), str(exc),
                          held_by="system", resume_condition="scope_or_terms_changed")
    return transition(db, row, "ready", "eligible",
                      "可准备标书，提交前由系统核验" if settings.BID_APPROVAL_MODE == 'automatic'
                      else "可准备标书，报价、周期和最终内容仍需审批",
                      held_by=None, resume_condition=None, resume_at=None)


def get_for_action(db, project_id, revision):
    project = db.query(Project).filter_by(freelancer_id=project_id).first()
    if project is None:
        raise LookupError("项目不在本地数据库中")
    row = ensure(db, project)
    db.flush()
    if row.revision != revision:
        raise RuntimeError("候选版本已变化，请刷新后重试")
    if db.query(BidSubmission).filter_by(project_freelancer_id=project_id).first() or row.state in {"submitted", "outcome_unknown"}:
        raise ValueError("已有提交记录或未知结果，不能通过队列恢复或修改")
    return project, row


def decide(db, project_id, revision, action, reason, resume_at=None):
    project, row = get_for_action(db, project_id, revision)
    if not reason.strip():
        raise ValueError("请填写处理原因")
    if action in {"defer", "reject"}:
        if resume_at is not None:
            resume_at = resume_at.astimezone(timezone.utc).replace(tzinfo=None)
            if resume_at <= now():
                raise ValueError("再次检查时间必须在未来")
        transition(db, row, "deferred" if action == "defer" else "rejected",
            "operator_deferred" if action == "defer" else "operator_rejected", reason.strip(),
            held_by="operator", resume_condition="time" if action == "defer" and resume_at else "manual",
            resume_at=resume_at if action == "defer" else None)
    elif action == "resume":
        if row.state not in {"deferred", "rejected"}:
            raise ValueError("只有暂缓或拒绝的候选可以恢复")
        invalidate_score(project)
        next_state = "needs_clarification" if object_value(row.questions) and not object_value(row.answers) else "needs_evaluation"
        transition(db, row, next_state, "operator_resumed", reason.strip(),
                   held_by=None, resume_condition=None, resume_at=None, approval_id=None)
    else:
        raise ValueError("不支持的队列操作")
    db.commit()
    return row


def resolve_questions(db, project_id, revision, answers):
    project, row = get_for_action(db, project_id, revision)
    questions = object_value(row.questions) or []
    if row.state != "needs_clarification" or not questions:
        raise ValueError("当前候选没有待解决的澄清问题")
    supplied = {answer["id"]: answer["answer"].strip() for answer in answers}
    if len(supplied) != len(answers) or set(supplied) != {q["id"] for q in questions} or not all(supplied.values()):
        raise ValueError("请完整回答当前版本的每个问题，不能遗漏或重复")
    contextual = [{"id": q["id"], "question": q["question"], "answer": supplied[q["id"]],
                   "source": "operator", "recorded_at": now().isoformat()} for q in questions]
    row.answers = json.dumps(contextual, ensure_ascii=False)
    invalidate_score(project)
    transition(db, row, "needs_evaluation", "clarification_answered", "信息已补充，等待重新评估工时与报价",
               held_by=None, resume_condition=None, resume_at=None, approval_id=None)
    event(db, "clarification", "answered", project_id=project_id)
    db.commit()
    return row


def require_preparable(db, project):
    row = db.query(CandidateWorkflow).filter_by(project_freelancer_id=project.freelancer_id).first()
    if row is not None:
        row = ensure(db, project)
    if row is not None and row.state not in {"ready", "awaiting_approval", "awaiting_submission"}:
        raise ValueError(f"候选尚不可准备：{row.reason}")
    if row is not None and row.state == "ready" and not score_is_current(project, policy_signature(db)):
        raise ValueError("候选评分已失效，请重新评估后准备标书")
    return row


def mark_prepared(db, project, approval_id, *, automatic=False):
    row = ensure(db, project)
    transition(db, row, "awaiting_submission" if automatic else "awaiting_approval", "prepared",
               "最终标书已准备，等待系统提交核验" if automatic else "最终标书已准备，等待 QQ 内容审批",
               approval_id=approval_id)
    event(db, "preparation", "prepared", project_id=project.freelancer_id,
          key=f"prepared:{approval_id}")


def reconcile(db):
    """Use authoritative submission rows and existing QQ decisions; never submit or resend."""
    from services.qqbot_service import QQBotConfig
    from services.qqbot_store import canonical_hash
    from config import settings
    config = QQBotConfig.from_env()
    rows = db.query(CandidateWorkflow).all()
    approvals = {}
    if Path(config.state_path).is_file():
        conn = sqlite3.connect(f"file:{Path(config.state_path).resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            for raw in conn.execute("SELECT * FROM approvals ORDER BY created_at DESC"):
                item = dict(raw)
                payload = json.loads(item["payload"])
                automatic = payload.get('authorization', {}).get('mode') == 'automatic'
                if (payload.get("account_id") != settings.FREELANCER_USER_ID
                        or (not automatic and (payload.get("qq_app_id") != config.app_id
                        or payload.get("qq_target_id") != config.target_id
                        or payload.get("qq_target_type") != config.target_type))
                        or canonical_hash(payload) != item["digest"]):
                    continue
                item["payload"] = payload
                approvals.setdefault(item["project_id"], item)
        finally:
            conn.close()
    for row in rows:
        project_id = row.project_freelancer_id
        submission = db.query(BidSubmission).filter_by(project_freelancer_id=project_id).first()
        if submission is not None:
            state = "submitted" if submission.status == "submitted" else "outcome_unknown"
            transition(db, row, state, submission.status, "已投标" if state == "submitted" else "提交结果未确认，禁止重发")
            continue
        if db.query(Bid).filter_by(project_freelancer_id=project_id).filter(Bid.status.in_(["active", "submitted", "submitted_remote_only"])).first():
            transition(db, row, "submitted", "bid_recorded", "已有投标记录")
            continue
        snapshot = approvals.get(project_id)
        if snapshot is None or row.approval_id != snapshot["id"]:
            continue
        state = snapshot["state"]
        if state == "rejected":
            transition(db, row, "rejected", "approval_rejected", "QQ 中已拒绝该候选",
                       held_by="operator", resume_condition="manual")
            event(db, "approval", "rejected", project_id=project_id, key=f"decision:{snapshot['id']}:rejected")
        elif state == "blocked":
            transition(db, row, "deferred", "approval_blocked", "执行前核验未通过，需要人工复核后恢复",
                       held_by="system", resume_condition="manual")
        elif state == "approved":
            event(db, "approval", "approved", project_id=project_id, key=f"decision:{snapshot['id']}:approved")
        if state in {"pending", "approved", "auto_pending", "auto_authorized"} and snapshot["expires_at"] <= time.time():
            if row.held_by != "operator":
                transition(db, row, "deferred", "approval_expired", "批准已过期，等待人工恢复并重新准备",
                           approval_id=None, held_by="system", resume_condition="manual")


def serialize(row, project):
    return {"project_id": row.project_freelancer_id, "title": project.title,
        "state": row.state, "reason_code": row.reason_code, "reason": row.reason,
        "revision": row.revision, "questions": object_value(row.questions) or [],
        "answers": object_value(row.answers) or [], "held_by": row.held_by,
        "resume_condition": row.resume_condition,
        "resume_at": row.resume_at.isoformat() + "Z" if row.resume_at else None,
        "approval_id": row.approval_id, "ai_score": project.ai_score,
        "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else None}


def statistics(db, since):
    grouped = db.query(WorkflowEvent.stage, WorkflowEvent.outcome, WorkflowEvent.reason_code,
                       func.sum(WorkflowEvent.count)).filter(WorkflowEvent.created_at >= since).group_by(
                           WorkflowEvent.stage, WorkflowEvent.outcome, WorkflowEvent.reason_code).all()
    state_counts = db.query(CandidateWorkflow.state, func.count(CandidateWorkflow.id)).group_by(CandidateWorkflow.state).all()
    runs = db.query(WorkflowRun).filter(WorkflowRun.started_at >= since).order_by(WorkflowRun.started_at.desc()).limit(20).all()
    score_events = db.query(WorkflowEvent).filter(WorkflowEvent.stage == "score", WorkflowEvent.created_at >= since).all()
    calls = hits = tokens = reuses = 0
    usage_complete = True
    for item in score_events:
        detail = object_value(item.details) or {}
        calls += detail.get("model_calls", 0)
        hits += int(detail.get("cache_hit", False))
        reuses += int(detail.get("assessment_reused", False))
        tokens += detail.get("tokens", 0)
        if detail.get("model_calls", 0) and not detail.get("usage_complete"):
            usage_complete = False
    from services.bid_outcome_service import outcome_summary
    return {"since": since.isoformat() + "Z", "queue": dict(state_counts),
        "bid_outcomes": outcome_summary(db),
        "stages": [{"stage": a, "outcome": b, "reason_code": c, "count": n} for a, b, c, n in grouped],
        "model_usage": {"calls": calls, "cache_hits": hits, "assessment_reuses": reuses, "observed_tokens": tokens,
                        "token_usage_complete": usage_complete, "cost": None},
        "runs": [{"id": r.id, "status": r.status, "started_at": r.started_at.isoformat() + "Z",
                  "duration_ms": r.duration_ms, "failed_stage": r.failed_stage,
                  "summary": object_value(r.summary)} for r in runs]}
