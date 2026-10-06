from typing import List
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    model: str


class Segment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str


class TranscriptionResponse(BaseModel):
    request_id: str
    language: str
    duration: float = Field(gt=0)
    processing_time: float = Field(ge=0)
    rtf: float = Field(ge=0)
    text: str
    segments: List[Segment]
