from pydantic import BaseModel, Field
from typing import Literal

class CheckinIn(BaseModel):
    qr_token: str = Field(min_length=20)
    session_id: int
    idempotency_key: str = Field(min_length=8,max_length=120)
    present_students: int|None = Field(default=None,ge=0)
    topic: str|None = Field(default=None,max_length=300)
    remarks: str|None = Field(default=None,max_length=2000)
class NetworkTestIn(BaseModel): address: str|None=None
class PolicyIn(BaseModel):
    early_minutes: int=Field(ge=0,le=60); grace_minutes: int=Field(ge=0,le=60); freshness_minutes: int=Field(ge=1,le=1440); allowed_cidrs: list[str]; trusted_proxy_cidrs: list[str]=[]
class CorrectionIn(BaseModel): reason: str=Field(min_length=5,max_length=2000); evidence: str|None=Field(default=None,max_length=4000)
class CorrectionDecision(BaseModel): result: Literal["ON_TIME","LATE","ABSENT_NO_CHECKIN","EXCUSED","REVIEW_REQUIRED"]; reason: str=Field(min_length=5,max_length=2000)

