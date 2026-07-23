"""
Custom exceptions for AI Gateway.

These exceptions wrap lower-level httpx exceptions and provide a
consistent interface to the rest of the application.
"""


class AIServiceException(Exception):
    """
    Base exception for all AI Gateway errors.
    """

    def __init__(self, message: str = "AI service error"):
        self.message = message
        super().__init__(message)


class AIConnectionException(AIServiceException):
    """
    Raised when an AI service cannot be reached.
    """

    def __init__(self, message: str = "Unable to connect to AI service"):
        super().__init__(message)


class AITimeoutException(AIServiceException):
    """
    Raised when an AI service times out.
    """

    def __init__(self, message: str = "AI service request timed out"):
        super().__init__(message)


class AIResponseException(AIServiceException):
    """
    Raised when an AI service returns a non-success HTTP response.
    """

    def __init__(
        self,
        status_code: int,
        detail: str | None = None,
    ):
        self.status_code = status_code
        self.detail = detail or "Unknown error"

        super().__init__(
            f"AI service returned HTTP {status_code}: {self.detail}"
        )


class AIInvalidResponseException(AIServiceException):
    """
    Raised when the AI service returns an unexpected or malformed response.
    """

    def __init__(self, message: str = "Invalid response received from AI service"):
        super().__init__(message)