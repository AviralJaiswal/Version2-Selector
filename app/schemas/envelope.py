from typing import Generic, Optional, TypeVar, Any
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ResponseEnvelope(BaseModel, Generic[T]):
    """Standardized JSON response envelope across all API routes."""

    success: bool = True
    code: int = 200
    message: str = "Operation completed successfully"
    data: Optional[T] = None
    error: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


def success_response(data: Any = None, message: str = "Success", code: int = 200) -> dict:
    """Helper to return standardized success dictionary containing envelope and root fields for frontend compatibility."""
    response = {
        "success": True,
        "code": code,
        "message": message,
        "data": data,
        "error": None
    }
    if isinstance(data, dict):
        # Merge top level fields for seamless backward compatibility
        for k, v in data.items():
            if k not in response:
                response[k] = v
    return response


def error_response(message: str = "Error occurred", code: int = 400, error_details: Optional[str] = None) -> dict:
    """Helper to return standardized error dictionary."""
    return {
        "success": False,
        "code": code,
        "message": message,
        "data": None,
        "error": error_details or message
    }
