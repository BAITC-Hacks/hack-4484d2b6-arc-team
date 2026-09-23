from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000)]
RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class ProposalStatus(StrEnum):
    SUBMITTED = "submitted"
    SELECTED = "selected"
    REJECTED = "rejected"


class MilestoneStatus(StrEnum):
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"


class ReadinessLevel(StrEnum):
    DRAFT = "draft"
    WORKING = "working"
    READY = "ready"
    PRIORITY = "priority"


class BusinessProfile(Model):
    id: str
    name: str
    industry: str
    contact: str
    is_demo: bool = True


class Team(Model):
    id: str
    name: str
    interests: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    is_demo: bool = True


class DemoProfiles(Model):
    businesses: list[BusinessProfile]
    teams: list[Team]


class TaskCard(Model):
    title: Text = ""
    context: Text = ""
    need: Text = ""
    users: Text = ""
    data: Text = ""
    constraints: Text = ""
    expected_result: Text = ""
    success_criteria: Text = ""
    contact: Text = ""
    interaction_format: Text = ""
    # Suggestions are separate from business requirements and do not earn points.
    ai_recommendations: list[Text] = Field(default_factory=list, max_length=20)


class Question(Model):
    id: RequiredText
    field: str
    text: RequiredText

    @model_validator(mode="after")
    def known_field(self):
        if self.field not in TaskCard.model_fields or self.field == "ai_recommendations":
            raise ValueError("Question must refer to a business field of TaskCard")
        return self


class RatingCategory(Model):
    key: str
    label: str
    points: int = Field(ge=0, le=100)
    maximum: int = Field(ge=0, le=100)


class Rating(Model):
    """Future server-generated result; step 1 does not calculate ratings."""

    score: int = Field(ge=0, le=100)
    level: ReadinessLevel
    categories: list[RatingCategory]
    missing_fields: list[str]


class DraftCreate(Model):
    original_text: RequiredText
    topic: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ""


class DraftUpdate(Model):
    draft_text: RequiredText | None = None
    topic: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    answers: dict[str, Text] | None = None
    proposed_card: TaskCard | None = None

    @model_validator(mode="after")
    def no_null_updates(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Use empty strings or objects to clear fields, not null")
        return self


class Task(Model):
    id: str
    business_id: str
    original_text: str
    draft_text: str
    topic: str
    questions: list[Question]
    answers: dict[str, str]
    proposed_card: TaskCard
    confirmed_card: TaskCard | None = None
    confirmed_rating: Rating | None = None
    published_card: TaskCard | None = None
    published_rating: Rating | None = None
    status: TaskStatus = TaskStatus.DRAFT
    confirmed_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class Proposal(Model):
    id: str
    task_id: str
    team_id: str
    idea: RequiredText
    plan: RequiredText
    timeline: RequiredText
    prototype_url: HttpUrl | None = None
    questions: Text = ""
    status: ProposalStatus = ProposalStatus.SUBMITTED
    created_at: datetime
    decided_at: datetime | None = None


class Milestone(Model):
    id: str
    proposal_id: str
    description: RequiredText
    result_url: HttpUrl | None = None
    status: MilestoneStatus = MilestoneStatus.SUBMITTED
    points_awarded: int = Field(default=0, ge=0)
    created_at: datetime
    confirmed_at: datetime | None = None
