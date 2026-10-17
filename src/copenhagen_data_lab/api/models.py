"""Validated models of StatBank metadata responses.

Only fields the pipeline relies on are mandatory; a response missing one of them is a
schema change and fails fast with :class:`MetadataError` instead of surfacing later as a
confusing KeyError.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class MetadataError(ValueError):
    """Table metadata is missing, malformed or inconsistent with expectations."""


class VariableValue(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1)
    text: str


class Variable(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1)
    text: str
    elimination: bool = False
    time: bool = False
    values: list[VariableValue] = Field(min_length=1)

    def codes(self) -> list[str]:
        return [v.id for v in self.values]

    def labels(self) -> dict[str, str]:
        return {v.id: v.text for v in self.values}


class Documentation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    url: str | None = None


class TableInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    text: str
    description: str = ""
    unit: str
    updated: datetime  # As reported by StatBank: Danish local time, no offset.
    active: bool = True
    suppressed_data_value: str | None = Field(default=None, alias="suppressedDataValue")
    documentation: Documentation | None = None
    variables: list[Variable] = Field(min_length=1)

    @classmethod
    def parse(cls, payload: object) -> TableInfo:
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise MetadataError(f"Unexpected tableinfo schema: {exc}") from exc

    def variable(self, variable_id: str) -> Variable:
        for variable in self.variables:
            if variable.id == variable_id:
                return variable
        known = ", ".join(v.id for v in self.variables)
        raise MetadataError(f"Variable {variable_id!r} not in table {self.id} (has: {known})")

    @property
    def time_variable(self) -> Variable:
        candidates = [v for v in self.variables if v.time]
        if len(candidates) != 1:
            raise MetadataError(f"Expected exactly one time variable, found {len(candidates)}")
        return candidates[0]
