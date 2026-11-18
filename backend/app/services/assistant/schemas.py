from typing import Any, Literal
from uuid import UUID

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
    request_id: UUID | None = None
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


class AssistantModification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "change_travel_pace", "change_budget", "change_duration", "change_preferences",
        "change_attractions",
    ]
    parameters: dict[str, Any] = Field(default_factory=dict)


class AssistantIntentOutput(BaseModel):
    """Strict, untrusted structured intent returned by the language model."""

    model_config = ConfigDict(extra="forbid")

    intent: Literal["conversation", "modify_trip", "unsupported"]
    action: Literal[
        "change_travel_pace", "change_budget", "change_duration", "change_preferences",
        "change_attractions",
    ] | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    modifications: list[AssistantModification] = Field(default_factory=list, max_length=5)
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
            if self.action is not None or self.parameters or self.modifications:
                raise ValueError("Non-modification intents cannot specify actions or parameters.")
            return self
        if self.modifications:
            if self.action is not None or self.parameters:
                raise ValueError("Multi-change intents must use modifications only.")
            if self.requires_clarification:
                raise ValueError("Clarification responses cannot contain executable modifications.")
            for item in self.modifications:
                AssistantIntentOutput.model_validate({
                    "intent": "modify_trip", "action": item.action,
                    "parameters": item.parameters, "requires_clarification": False,
                    "clarification_question": None, "response": self.response,
                })
            return self
        if self.action is None:
            raise ValueError("Modification intent requires an allowlisted action.")

        allowed = {
            "change_travel_pace": {"pace"},
            "change_budget": {"amount_inr", "adjustment", "currency"},
            "change_duration": {"duration_days", "direction", "additional_context"},
            "change_preferences": {
                "interests", "walking_tolerance", "crowd_tolerance", "risk_tolerance",
                "transportation_mode",
            },
            "change_attractions": {
                "operation", "attraction_name", "target_name", "replacement_name", "category",
                "count", "day_number", "position", "criterion",
            },
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
            direction = self.parameters.get("direction")
            if "direction" in self.parameters and direction not in {"extend", "shorten"}:
                raise ValueError("Duration direction must be extend or shorten.")
            context = self.parameters.get("additional_context")
            if "additional_context" in self.parameters and (
                not isinstance(context, str) or len(context) > 300
            ):
                raise ValueError("Duration context must be at most 300 characters.")
            allowed_duration_parameters = {"duration_days", "direction", "additional_context"}
            if set(self.parameters) - allowed_duration_parameters:
                raise ValueError("Unexpected duration parameter.")
            if not self.requires_clarification and not {"duration_days", "direction"}.issubset(self.parameters):
                raise ValueError("Requested duration and direction are required.")
        elif self.action == "change_preferences":
            interest_values = self.parameters.get("interests")
            supported_interests = {
                "history", "heritage", "spiritual", "mountains", "nature", "adventure",
                "photography", "food", "wellness", "shopping", "nightlife", "beaches",
            }
            if "interests" in self.parameters:
                if (
                    not isinstance(interest_values, dict)
                    or not interest_values
                    or len(interest_values) > len(supported_interests)
                    or any(
                        key not in supported_interests
                        or isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not 0 <= value <= 1
                        for key, value in interest_values.items()
                    )
                ):
                    raise ValueError("Interest weights must use supported categories and values from 0 to 1.")
            for key in ("walking_tolerance", "crowd_tolerance", "risk_tolerance"):
                value = self.parameters.get(key)
                if key in self.parameters and (
                    isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1
                ):
                    raise ValueError(f"{key} must be between 0 and 1.")
            if "transportation_mode" in self.parameters and self.parameters["transportation_mode"] not in {"walk", "car", "mixed"}:
                raise ValueError("Transportation mode must be walk, car, or mixed.")
            if not self.requires_clarification and not self.parameters:
                raise ValueError("At least one supported preference change is required.")
        elif self.action == "change_attractions":
            params = self.parameters
            operation = params.get("operation")
            categories = {
                "history", "heritage", "spiritual", "mountains", "nature", "adventure",
                "photography", "food", "wellness", "shopping", "nightlife", "beaches",
            }
            if operation is not None and operation not in {"add", "remove", "replace"}:
                raise ValueError("Attraction operation must be add, remove, or replace.")
            if "category" in params and params["category"] not in categories:
                raise ValueError("Unsupported attraction category.")
            for key in ("attraction_name", "target_name", "replacement_name"):
                value = params.get(key)
                if key in params and (not isinstance(value, str) or not value.strip() or len(value) > 150):
                    raise ValueError(f"{key} must be a non-empty attraction name.")
            if "count" in params and (
                isinstance(params["count"], bool) or not isinstance(params["count"], int)
                or not 1 <= params["count"] <= 3
            ):
                raise ValueError("At most three attractions can be requested at once.")
            if "day_number" in params and (
                isinstance(params["day_number"], bool) or not isinstance(params["day_number"], int)
                or not 1 <= params["day_number"] <= 60
            ):
                raise ValueError("Invalid itinerary day number.")
            if "position" in params and params["position"] != "last":
                raise ValueError("Only the last itinerary stop can be targeted by position.")
            if "criterion" in params and params["criterion"] not in {"nearby", "less_crowded"}:
                raise ValueError("Unsupported replacement criterion.")
            if self.requires_clarification:
                pass
            elif operation == "add":
                if bool(params.get("attraction_name")) == bool(params.get("category")):
                    raise ValueError("Adding attractions requires either a catalog name or category.")
                if params.get("attraction_name") and params.get("count", 1) != 1:
                    raise ValueError("A specific attraction request can add only one attraction.")
                if any(key in params for key in ("target_name", "replacement_name", "position", "criterion")):
                    raise ValueError("Unexpected target for an add operation.")
            elif operation == "remove":
                has_name = bool(params.get("target_name"))
                has_last = params.get("position") == "last" and "day_number" in params
                if has_name == has_last or any(key in params for key in ("attraction_name", "replacement_name", "category", "count", "criterion")):
                    raise ValueError("Removing attractions requires one target name or a day and last position.")
            elif operation == "replace":
                has_target = bool(params.get("target_name"))
                has_last = params.get("position") == "last" and "day_number" in params
                if has_target == has_last or any(key in params for key in ("attraction_name", "count")):
                    raise ValueError("Replacing attractions requires one target name or a day and last position.")
                if params.get("replacement_name") and params.get("category"):
                    raise ValueError("Choose a catalog replacement name or category, not both.")
            else:
                raise ValueError("Attraction operation is required.")
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
