from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AgentToolSchema(BaseModel):
    """A single agent-visible tool contract."""

    name: str
    mode: Literal["read"] = "read"
    description: str
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    data_sources: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def name_must_be_read_namespace(cls, value: str) -> str:
        if "." not in value:
            raise ValueError("tool name must use a namespace")
        action = value.rsplit(".", 1)[-1]
        if action not in {"read", "leaderboard", "search", "export"}:
            raise ValueError(f"tool action is not read-only: {action}")
        return value


class ReadonlyManifest(BaseModel):
    """Agent-safe manifest: only read/export/search/status tools."""

    name: str = "hypersmart-agent-safe-readonly"
    version: str = "1.0"
    mode: Literal["read_only"] = "read_only"
    custody: Literal["zero_custody"] = "zero_custody"
    simulation: Literal["paper_mock_usdc_only"] = "paper_mock_usdc_only"
    tools: list[AgentToolSchema]
    forbidden_capabilities: list[str] = Field(default_factory=list)

    def tool_names(self) -> set[str]:
        return {tool.name for tool in self.tools}

