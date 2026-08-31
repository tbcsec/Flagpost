"""Schemas for per-competition custom registration fields (#350)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FieldType = Literal["text", "textarea", "select", "checkbox"]


class RegistrationFieldIn(BaseModel):
    """One field definition, as authored by an organiser."""

    # Stable machine handle values are keyed by. Constrained so it's safe as a
    # JSON key and a form field name.
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=1, max_length=200)
    field_type: FieldType = "text"
    options: list[str] = Field(default_factory=list, max_length=100)
    required: bool = False
    position: int = 0

    @field_validator("options", mode="before")
    @classmethod
    def _options_default(cls, v: object) -> object:
        return v or []  # null (from the ORM / a non-select field) → []

    @model_validator(mode="after")
    def _check_options(self) -> "RegistrationFieldIn":
        if self.field_type == "select":
            self.options = [o.strip() for o in self.options if o.strip()]
            if not self.options:
                raise ValueError("A select field needs at least one option")
        else:
            # Options are meaningless off a select — normalize them away so a
            # stored row can never imply choices it doesn't enforce.
            self.options = []
        return self


class RegistrationFieldOut(RegistrationFieldIn):
    model_config = ConfigDict(from_attributes=True)

    id: str


class RegistrationFieldsUpdate(BaseModel):
    """Replace-all set of a competition's field definitions (like the managed
    vocab). Values are keyed by field ``key``, so replacing the set keeps a
    subject's answers addressable as long as the key is unchanged."""

    fields: list[RegistrationFieldIn] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _unique_keys(self) -> "RegistrationFieldsUpdate":
        keys = [f.key for f in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("Field keys must be unique within a competition")
        return self


class RegistrationValuesIn(BaseModel):
    """A subject's submitted answers: ``{field_key: value}``. Coerced + validated
    against the field definitions at the boundary (``utils/registration_fields``)."""

    values: dict[str, object] = Field(default_factory=dict)


class RegistrationValuesOut(BaseModel):
    values: dict[str, object] = Field(default_factory=dict)


class EntryFieldValues(BaseModel):
    """Custom-field answers submitted *at entry* (individual join / team create).
    Optional so an entry into a competition with no fields carries nothing."""

    field_values: dict[str, object] = Field(default_factory=dict)
