"""
Common API response helpers.
"""

from typing import Any


def success_response(
    data: Any = None,
    message: str = "Success",
) -> dict:
    """
    Standard success response.
    """

    return {
        "success": True,
        "message": message,
        "data": data,
    }


def error_response(
    message: str,
    error: str,
) -> dict:
    """
    Standard error response.
    """

    return {
        "success": False,
        "error": error,
        "message": message,
    }