"""
AI 回复生成 API。

功能：
- 对输入的上下文消息进行脱敏（邮箱/电话/URL/信用卡号）
- 调用 LLM 生成 3 种语气候选回复（professional/enthusiastic/concise）
- 将候选回复写入数据库，并记录审计日志
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional

from database.connection import get_db_session
from database.models import AIReplyOption, AuditLog, MessageThread
from services.llm_client import get_llm_client, LLMClientProtocol, LLMError
from utils.redaction import desensitize_obj
from config import settings


router = APIRouter()


class AIRepliesRequest(BaseModel):
    """AI 回复生成请求体。"""

    thread_id: int = Field(..., gt=0, description="Freelancer 线程 ID")
    context_messages: List[Dict[str, Any]] = Field(default_factory=list, description="对话上下文消息列表")


class AIReplyItem(BaseModel):
    """单条候选回复。"""

    id: Optional[int] = None
    tone: Literal["professional", "enthusiastic", "concise"]
    text: str


class AIRepliesResponse(BaseModel):
    """AI 回复生成响应体。"""

    thread_id: int
    replies: List[AIReplyItem]


@router.post("/replies", response_model=AIRepliesResponse)
async def generate_ai_replies(
    request: AIRepliesRequest,
    llm: LLMClientProtocol = Depends(get_llm_client),
):
    """
    生成 3 种语气的 AI 回复候选项。

    - 在调用 LLM 前，对 `context_messages` 内所有字符串字段进行脱敏
    - 生成结果会写入 `ai_reply_options` 表，并写入 `audit_logs` 便于追踪
    """
    # 1) 脱敏（避免把敏感信息发给 LLM）
    masked_context = desensitize_obj(request.context_messages)

    try:
        # 2) 调用 LLM（测试环境会通过依赖覆盖注入 Fake）
        raw_replies = await llm.generate_replies(thread_id=request.thread_id, context_messages=masked_context)

        # 3) 规范化与校验
        tone_map = {
            "professional": "professional",
            "enthusiastic": "enthusiastic",
            "concise": "concise",
        }

        normalized: List[AIReplyItem] = []
        for item in raw_replies:
            tone = str(item.get("tone", "")).strip()
            text = str(item.get("text", "")).strip()
            if tone not in tone_map or not text:
                continue
            normalized.append(AIReplyItem(tone=tone_map[tone], text=text))

        if len(normalized) < 3:
            raise HTTPException(status_code=502, detail="LLM returned insufficient replies")

        normalized = normalized[:3]

        # 4) 写入数据库 + 审计日志
        with get_db_session() as db:
            # 若线程不存在，创建最小线程记录（避免外键约束/后续查询缺失）
            thread = db.query(MessageThread).filter_by(freelancer_thread_id=request.thread_id).first()
            if not thread:
                thread = MessageThread(freelancer_thread_id=request.thread_id)
                db.add(thread)
                db.flush()

            for r in normalized:
                option = AIReplyOption(
                    thread_id=request.thread_id,
                    tone=r.tone,
                    text=r.text,
                    provider=getattr(settings, "LLM_PROVIDER", "openai"),
                    model=getattr(settings, "LLM_MODEL", "gpt-4o-mini"),
                    context_messages_masked=str(masked_context),
                )
                db.add(option)
                db.flush() # 获取 ID
                r.id = option.id

            db.add(
                AuditLog(
                    action="generate_ai_replies",
                    entity_type="message_thread",
                    entity_id=request.thread_id,
                    request_data=str({"thread_id": request.thread_id, "context_messages": masked_context}),
                    response_data=str([r.model_dump() for r in normalized]),
                    status="success",
                )
            )

        return AIRepliesResponse(thread_id=request.thread_id, replies=normalized)

    except HTTPException:
        raise
    except LLMError as e:
        # LLM 失败也记录审计日志（便于排查）
        with get_db_session() as db:
            db.add(
                AuditLog(
                    action="generate_ai_replies",
                    entity_type="message_thread",
                    entity_id=request.thread_id,
                    request_data=str({"thread_id": request.thread_id, "context_messages": masked_context}),
                    response_data="",
                    status="error",
                    error_message=e.message,
                )
            )
        raise HTTPException(status_code=e.status_code or 502, detail=e.message)
    except Exception as e:
        with get_db_session() as db:
            db.add(
                AuditLog(
                    action="generate_ai_replies",
                    entity_type="message_thread",
                    entity_id=request.thread_id,
                    request_data=str({"thread_id": request.thread_id, "context_messages": masked_context}),
                    response_data="",
                    status="error",
                    error_message=str(e),
                )
            )
        raise HTTPException(status_code=500, detail=f"Failed to generate AI replies: {e}")

