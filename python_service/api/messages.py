"""
Messages API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from typing import Optional, List, Any
from pydantic import BaseModel, Field
from datetime import datetime

from database.connection import get_db, get_db_session
from database.models import Message, MessageThread, Project, AuditLog, AIReplyOption
from services.freelancer_client import get_freelancer_client, FreelancerAPIError
import os
import hashlib
import json

router = APIRouter()


# Pydantic models
class SendMessageRequest(BaseModel):
    """Request model for sending a message."""
    thread_id: Optional[int] = None
    to_user_id: Optional[int] = None
    message: str = Field(min_length=1, max_length=10000)


class APIResponse(BaseModel):
    """Standard API response wrapper."""
    status: str
    data: Any


@router.post("", response_model=APIResponse)
async def send_message(request: SendMessageRequest):
    """
    Send a message to a thread or user.

    Request Body:
    - thread_id: Message thread ID (optional, mutually exclusive with to_user_id)
    - to_user_id: Recipient user ID (optional, mutually exclusive with thread_id)
    - message: Message content
    """
    if not request.thread_id and not request.to_user_id:
        raise HTTPException(
            status_code=400,
            detail="Either thread_id or to_user_id must be provided"
        )

    try:
        client = get_freelancer_client()

        # Send via Freelancer API
        result = await client.send_message(
            thread_id=request.thread_id,
            to_user_id=request.to_user_id,
            message=request.message
        )

        # Store in database
        with get_db_session() as db:
            message = Message(
                freelancer_message_id=result.get('message_id', {}).get('id') if result else 0,
                thread_id=request.thread_id if request.thread_id else result.get('thread_id'),
                user_id=result.get('user', {}).get('id') if result else 0,
                username=result.get('user', {}).get('name') if result else '',
                message=request.message,
                send_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            )
            db.add(message)
            db.commit()

            # Update thread if exists
            if request.thread_id:
                thread = db.query(MessageThread).filter_by(
                    freelancer_thread_id=request.thread_id
                ).first()
                if thread:
                    thread.last_message_time = message.send_time
                    thread.last_message_preview = request.message[:100]
                    thread.updated_at = datetime.utcnow()
            elif result.get('thread_id'):
                # Create new thread record
                thread = MessageThread(
                    freelancer_thread_id=result.get('thread_id'),
                    participants=str([result.get('user', {}).get('id')]),
                    last_message_time=message.send_time,
                    last_message_preview=request.message[:100]
                )
                db.add(thread)

            # Audit log
            audit = AuditLog(
                action="send_message",
                entity_type="message",
                entity_id=message.freelancer_message_id,
                request_data=str(request.dict()),
                response_data=str(result),
                status="success"
            )
            db.add(audit)
            db.commit()

        return APIResponse(
            status="success",
            data={
                "message_id": message.freelancer_message_id,
                "thread_id": request.thread_id or result.get('thread_id'),
                "sent_at": message.send_time
            }
        )

    except HTTPException:
        raise
    except FreelancerAPIError as e:
        with get_db_session() as db:
            audit = AuditLog(
                action="send_message",
                entity_type="message",
                entity_id=0,
                request_data=str(request.dict()),
                response_data=str(e.message),
                status="error",
                error_message=e.message
            )
            db.add(audit)
            db.commit()

        raise HTTPException(status_code=e.status_code or 500, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send message: {str(e)}")


@router.post("/sync", response_model=APIResponse)
async def sync_messages():
    """
    Synchronize messages from Freelancer.
    
    Logic:
    1. Fetch latest threads.
    2. For each thread, fetch latest messages.
    3. Deduplicate and store new messages.
    4. Update thread status (unread count, last message).
    """
    try:
        client = get_freelancer_client()
        new_messages_count = 0
        updated_threads_count = 0

        # 1. Fetch threads
        threads = await client.get_threads(limit=20)
        
        with get_db_session() as db:
            for t_data in threads:
                thread_id = t_data.get('id')
                if not thread_id:
                    continue

                # Update or create thread
                thread = db.query(MessageThread).filter_by(
                    freelancer_thread_id=thread_id
                ).first()

                participants = [m.get('id') for m in t_data.get('members', [])]
                
                if not thread:
                    thread = MessageThread(
                        freelancer_thread_id=thread_id,
                        project_freelancer_id=t_data.get('project_id'),
                        participants=str(participants),
                        created_at=datetime.utcnow()
                    )
                    db.add(thread)
                else:
                    thread.participants = str(participants)
                
                thread.unread_count = t_data.get('unread_count', 0)
                thread.last_message_time = t_data.get('last_message_date')
                thread.updated_at = datetime.utcnow()
                updated_threads_count += 1

                # 2. Fetch messages for this thread
                # Only if unread > 0 or it's a new thread or check if we are missing messages?
                # For simplicity, always sync latest 20 messages for active threads
                # To optimize, we could check last_message_time vs DB
                
                messages = await client.get_messages(thread_id, limit=20)
                
                for m_data in messages:
                    msg_id = m_data.get('id')
                    content = m_data.get('message', '')
                    
                    # Generate hash for dedup
                    content_hash = hashlib.md5(
                        f"{thread_id}:{content}:{m_data.get('date')}".encode()
                    ).hexdigest()

                    # Check existence
                    existing = db.query(Message).filter(
                        (Message.freelancer_message_id == msg_id)
                    ).first()

                    if not existing:
                        # Insert new message
                        new_msg = Message(
                            freelancer_message_id=msg_id,
                            thread_id=thread_id,
                            user_id=m_data.get('from_user'),
                            username=str(m_data.get('from_user')), # Name might be separate
                            message=content,
                            send_time=m_data.get('date'),
                            is_read=False, # Default to unread for new sync
                            created_at=datetime.utcnow()
                        )
                        
                        # Handle attachments if any
                        if m_data.get('attachments'):
                            att = m_data['attachments'][0]
                            new_msg.attachment_url = att.get('url')
                            new_msg.attachment_name = att.get('filename')

                        db.add(new_msg)
                        new_messages_count += 1
                        
                        # Update thread preview
                        thread.last_message_preview = content[:100]

            db.commit()

        return APIResponse(
            status="success",
            data={
                "new_messages_count": new_messages_count,
                "updated_threads_count": updated_threads_count
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync messages: {str(e)}")


@router.get("/unread", response_model=APIResponse)
async def get_unread_messages(
    limit: int = Query(default=20, ge=1, le=100)
):
    """
    Get all threads with unread messages and their latest unread messages.
    """
    try:
        with get_db_session() as db:
            # Get unread threads
            threads = db.query(MessageThread).filter(
                MessageThread.unread_count > 0
            ).order_by(MessageThread.last_message_time.desc()).limit(limit).all()

            result_threads = []
            for t in threads:
                # Get latest unread messages for this thread
                msgs = db.query(Message).filter_by(
                    thread_id=t.freelancer_thread_id,
                    is_read=False
                ).order_by(Message.send_time.desc()).limit(5).all()

                result_threads.append({
                    "thread_id": t.freelancer_thread_id,
                    "project_id": t.project_freelancer_id,
                    "unread_count": t.unread_count,
                    "last_message_time": t.last_message_time,
                    "messages": [m.to_dict() for m in msgs]
                })

        return APIResponse(
            status="success",
            data={
                "threads": result_threads,
                "total": len(threads)
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get unread messages: {str(e)}")


class TelegramCallbackRequest(BaseModel):
    """Request model for Telegram callback."""
    callback_data: str


@router.post("/telegram/callback", response_model=APIResponse)
async def telegram_callback(request: TelegramCallbackRequest):
    """
    Handle Telegram callback queries from inline buttons.
    
    Format: action:thread_id:reply_id
    """
    try:
        parts = request.callback_data.split(":")
        if len(parts) < 2:
            raise HTTPException(status_code=400, detail="Invalid callback data format")
        
        action = parts[0]
        thread_id = int(parts[1])
        reply_id = int(parts[2]) if len(parts) > 2 else None

        client = get_freelancer_client()
        
        with get_db_session() as db:
            if action == "send":
                if not reply_id:
                    raise HTTPException(status_code=400, detail="Reply ID missing for send action")
                
                # Get reply from DB
                reply_option = db.query(AIReplyOption).filter_by(id=reply_id).first()
                if not reply_option:
                    raise HTTPException(status_code=404, detail="AI reply option not found")
                
                # Send to Freelancer
                result = await client.send_message(
                    thread_id=thread_id,
                    message=reply_option.text
                )
                
                # Mark thread as read locally
                thread = db.query(MessageThread).filter_by(freelancer_thread_id=thread_id).first()
                if thread:
                    thread.unread_count = 0
                
                # Save outgoing message to DB
                new_msg = Message(
                    freelancer_message_id=result.get('message_id', {}).get('id', 0),
                    thread_id=thread_id,
                    user_id=client.user_id,
                    username="Me (AI)",
                    message=reply_option.text,
                    send_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    is_read=True
                )
                db.add(new_msg)
                
                # Audit
                audit = AuditLog(
                    action="telegram_reply_send",
                    entity_type="message",
                    entity_id=thread_id,
                    request_data=request.callback_data,
                    response_data=str(result),
                    status="success"
                )
                db.add(audit)
                db.commit()
                
                return APIResponse(status="success", data={"message": "Reply sent successfully"})
                
            elif action == "ignore":
                # Mark thread as read
                thread = db.query(MessageThread).filter_by(freelancer_thread_id=thread_id).first()
                if thread:
                    thread.unread_count = 0
                    thread.updated_at = datetime.utcnow()
                
                db.commit()
                return APIResponse(status="success", data={"message": "Thread marked as ignored/read"})
            
            else:
                raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    except Exception as e:
        logger.error(f"Telegram callback error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload", response_model=APIResponse)
async def upload_attachment(
    file: UploadFile = File(...),
    thread_id: int = Query(..., gt=0)
):
    """
    Upload an attachment to a message thread.

    Query Parameters:
    - thread_id: Target message thread ID

    Form Data:
    - file: Attachment file to upload
    """
    try:
        client = get_freelancer_client()

        # Save uploaded file temporarily
        upload_dir = "/app/data/uploads"
        os.makedirs(upload_dir, exist_ok=True)

        file_path = os.path.join(upload_dir, file.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())

        # Upload via Freelancer API
        result = await client.upload_attachment(file_path, thread_id)

        # Clean up temp file
        os.remove(file_path)

        # Store in database
        with get_db_session() as db:
            attachment_url = result.get('attachment_url', '')

            message = Message(
                freelancer_message_id=0,
                thread_id=thread_id,
                message=f"[Attachment: {file.filename}]",
                attachment_url=attachment_url,
                attachment_name=file.filename,
                send_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            )
            db.add(message)
            db.commit()

            # Update thread
            thread = db.query(MessageThread).filter_by(
                freelancer_thread_id=thread_id
            ).first()
            if thread:
                thread.last_message_time = message.send_time
                thread.last_message_preview = f"[Attachment: {file.filename}]"
                thread.updated_at = datetime.utcnow()

            # Audit log
            audit = AuditLog(
                action="upload_attachment",
                entity_type="message",
                entity_id=0,
                request_data=f"thread_id={thread_id}, filename={file.filename}",
                response_data=str(result),
                status="success"
            )
            db.add(audit)
            db.commit()

        return APIResponse(
            status="success",
            data={
                "attachment_url": attachment_url,
                "thread_id": thread_id
            }
        )

    except FreelancerAPIError as e:
        with get_db_session() as db:
            audit = AuditLog(
                action="upload_attachment",
                entity_type="message",
                entity_id=thread_id,
                request_data=f"filename={file.filename}",
                response_data=str(e.message),
                status="error",
                error_message=e.message
            )
            db.add(audit)
            db.commit()

        raise HTTPException(status_code=e.status_code or 500, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload attachment: {str(e)}")


@router.get("/threads", response_model=APIResponse)
async def get_threads(
    project_id: Optional[int] = None,
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0)
):
    """
    Get message threads.

    Query Parameters:
    - project_id: Filter by project ID
    - unread_only: Only show unread threads
    - limit: Number of results (1-200, default: 50)
    - offset: Pagination offset (default: 0)
    """
    try:
        with get_db_session() as db:
            query = db.query(MessageThread)

            if project_id:
                # First get internal project ID
                project = db.query(Project).filter_by(
                    freelancer_id=project_id
                ).first()
                if project:
                    query = query.filter(MessageThread.project_id == project.id)

            if unread_only:
                query = query.filter(MessageThread.unread_count > 0)

            # Get total count
            total = query.count()

            # Apply pagination
            threads = query.order_by(MessageThread.last_message_time.desc()).offset(offset).limit(limit).all()

        return APIResponse(
            status="success",
            data=[
                {
                    "thread_id": t.freelancer_thread_id,
                    "project_id": t.project_freelancer_id,
                    "participants": t.participants,
                    "last_message_time": t.last_message_time,
                    "last_message_preview": t.last_message_preview,
                    "unread_count": t.unread_count
                }
                for t in threads
            ],
            total=total
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get threads: {str(e)}")


@router.get("/{thread_id}", response_model=APIResponse)
async def get_thread_messages(
    thread_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0)
):
    """
    Get messages from a specific thread.

    Path Parameters:
    - thread_id: Message thread ID

    Query Parameters:
    - limit: Number of messages (1-200, default: 50)
    - offset: Pagination offset (default: 0)
    """
    try:
        with get_db_session() as db:
            messages = db.query(Message).filter_by(thread_id=thread_id).order_by(
                Message.send_time.asc()
            ).offset(offset).limit(limit).all()

            # Mark as read
            db.query(Message).filter_by(thread_id=thread_id).update({
                "is_read": True
            })

        return APIResponse(
            status="success",
            data=[m.to_dict() for m in messages],
            total=len(messages)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get messages: {str(e)}")


@router.put("/{thread_id}/read", response_model=APIResponse)
async def mark_thread_read(thread_id: int):
    """
    Mark a thread as read (reset unread count).

    Path Parameters:
    - thread_id: Message thread ID
    """
    try:
        with get_db_session() as db:
            thread = db.query(MessageThread).filter_by(
                freelancer_thread_id=thread_id
            ).first()

            if thread:
                thread.unread_count = 0
                thread.updated_at = datetime.utcnow()
                db.commit()

        return APIResponse(
            status="success",
            data={"message": "Thread marked as read"}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to mark thread read: {str(e)}")
