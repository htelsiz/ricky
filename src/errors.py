"""Exception hierarchy for ricky."""


class RickyError(Exception):
    """Base exception for all ricky errors."""


class ConfigError(RickyError):
    """Missing or invalid configuration (env vars, secret files)."""


class ServiceError(RickyError):
    """Base for all service communication errors."""

    def __init__(self, service: str, message: str) -> None:
        self.service = service
        super().__init__(f"{service}: {message}")


class AuthenticationError(ServiceError):
    """Authentication failed (bad credentials or expired token)."""


class NotFoundError(ServiceError):
    """Requested resource was not found."""


class ApiResponseError(ServiceError):
    """Unexpected HTTP response from a service."""

    def __init__(self, service: str, status_code: int, body: str = "") -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(service, f"HTTP {status_code}: {body[:200]}")
