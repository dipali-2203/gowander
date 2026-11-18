from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AssistantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2_000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message content cannot be blank.")
        return value


class AssistantChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2_000)
    trip_id: int | None = Field(default=None, gt=0)
    conversation_history: list[AssistantMessage] = Field(default_factory=list, max_length=16)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be blank.")
        return value

    @model_validator(mode="after")
    def limit_history_size(self):
        if sum(len(item.content) for item in self.conversation_history) > 12_000:
            raise ValueError("Conversation history is too long. Start a new conversation.")
        return self
        return self


class AssistantChatResponse(BaseModel):
    response: str = Field(min_length=1, max_length=2_000)
    conversation_id: str | None = None
    suggested_actions: list[str] = Field(default_factory=list)
