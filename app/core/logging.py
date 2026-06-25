import logging
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s",
    )


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


def new_request_id() -> str:
    rid = str(uuid.uuid4())[:8]
    request_id_var.set(rid)
    return rid
