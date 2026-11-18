from typing import Any, Literal

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
    proposal: dict[str, Any] | None = None


class AssistantIntentOutput(BaseModel):
    """Strict, untrusted structured intent returned by the language model."""

    model_config = ConfigDict(extra="forbid")

    intent: Literal["conversation", "modify_trip", "unsupported"]
    action: Literal["change_travel_pace", "change_budget", "change_duration"] | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    requires_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=500)
    response: str = Field(min_length=1, max_length=2_000)

    @field_validator("response")
    @classmethod
    def response_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Assistant response cannot be blank.")
        return value

    @model_validator(mode="after")
    def validate_allowlisted_action_parameters(self):
        if self.intent != "modify_trip":
            if self.action is not None or self.parameters:
                raise ValueError("Non-modification intents cannot specify actions or parameters.")
            return self
        if self.action is None:
            raise ValueError("Modification intent requires an allowlisted action.")

        allowed = {
            "change_travel_pace": {"pace"},
            "change_budget": {"amount_inr", "adjustment", "currency"},
            "change_duration": {"duration_days"},
        }[self.action]
        if set(self.parameters) - allowed:
            raise ValueError("Unexpected modification parameter.")
        if self.action == "change_travel_pace":
            pace = self.parameters.get("pace")
            if "pace" in self.parameters and (not isinstance(pace, str) or pace not in {"relaxed", "balanced", "fast"}):
                raise ValueError("Invalid travel pace parameters.")
            if not self.requires_clarification and set(self.parameters) != {"pace"}:
                raise ValueError("Travel pace is required.")
        elif self.action == "change_budget":
            amount = self.parameters.get("amount_inr")
            if "amount_inr" in self.parameters and (
                isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 1 <= amount <= 5_000_000
            ):
                raise ValueError("Budget amount must be between INR 1 and INR 5,000,000.")
            adjustment = self.parameters.get("adjustment")
            if "adjustment" in self.parameters and (
                not isinstance(adjustment, str) or adjustment not in {"set", "increase_by", "decrease_by"}
            ):
                raise ValueError("Invalid budget adjustment.")
            if self.parameters.get("currency", "INR") != "INR":
                raise ValueError("Only INR budgets are supported.")
            if not self.requires_clarification and set(self.parameters) - {"currency"} != {"amount_inr", "adjustment"}:
                raise ValueError("Budget amount and adjustment are required.")
        elif self.action == "change_duration":
            days = self.parameters.get("duration_days")
            if "duration_days" in self.parameters and (
                isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 60
            ):
                raise ValueError("Duration must be between 1 and 60 days.")
            if not self.requires_clarification and set(self.parameters) != {"duration_days"}:
                raise ValueError("Duration is required.")
        if self.requires_clarification:
            if not self.clarification_question:
                raise ValueError("Clarification requires a question.")
        elif self.clarification_question is not None:
            raise ValueError("Clarification question is only valid when clarification is required.")
        return self


def assistant_intent_response_json_schema() -> dict[str, Any]:
    """Return the Pydantic schema with only Gemini responseJsonSchema keywords."""
    supported = {
        "$id", "$defs", "$ref", "$anchor", "type", "format", "title", "description",
        "enum", "items", "prefixItems", "minItems", "maxItems", "minimum", "maximum",
        "anyOf", "oneOf", "properties", "additionalProperties", "required", "propertyOrdering",
    }

    def prune(value: Any) -> Any:
        if isinstance(value, list):
            return [prune(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in {"properties", "$defs"} and isinstance(item, dict):
                result[key] = {name: prune(schema) for name, schema in item.items()}
            elif key in supported:
                result[key] = prune(item)
        return result

    return prune(AssistantIntentOutput.model_json_schema())
