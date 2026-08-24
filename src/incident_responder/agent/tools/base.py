from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    tool: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "success": self.success, "summary": self.summary, "data": self.data}
