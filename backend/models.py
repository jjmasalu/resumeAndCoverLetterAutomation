from pydantic import BaseModel, Field
from enum import Enum


class ConversationMode(str, Enum):
    job_to_resume = "job_to_resume"
    find_jobs = "find_jobs"


class ConversationStatus(str, Enum):
    active = "active"
    completed = "completed"


class DocType(str, Enum):
    resume = "resume"
    cover_letter = "cover_letter"


class CreateConversationRequest(BaseModel):
    mode: ConversationMode


class SendMessageRequest(BaseModel):
    content: str
    attachment_file_ids: list[str] = Field(default_factory=list)


class VerifyTeamAccessRequest(BaseModel):
    code: str


class ConversationResponse(BaseModel):
    id: str
    mode: ConversationMode
    title: str
    status: ConversationStatus
    created_at: str


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    metadata: dict = {}
    created_at: str


class DocumentResponse(BaseModel):
    id: str
    job_id: str
    doc_type: DocType
    file_url: str
    created_at: str


class UploadFileResponse(BaseModel):
    file_id: str
    filename: str
    gemini_file_uri: str


class UpdateProfileRequest(BaseModel):
    full_name: str


class UpdateUserContextRequest(BaseModel):
    content: dict


class BulkDeleteConversationsRequest(BaseModel):
    conversation_ids: list[str]
