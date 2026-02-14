"""Custom error hierarchy for Ricky."""


class AgentError(Exception):
    """Base error for all Ricky operations."""


class GitHubError(AgentError):
    """GitHub API call failed."""

    def __init__(self, status: int, message: str, endpoint: str = ""):
        self.status = status
        self.endpoint = endpoint
        super().__init__(f"GitHub {status} on {endpoint}: {message}")


class GeminiError(AgentError):
    """Gemini / Vertex AI call failed."""

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"Gemini {status}: {message}")


class ToolError(AgentError):
    """A tool failed during execution."""

    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        super().__init__(f"[{tool_name}] {message}")
