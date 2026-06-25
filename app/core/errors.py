from typing import Any


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def error_response(code: str, message: str, request_id: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "request_id": request_id}}
