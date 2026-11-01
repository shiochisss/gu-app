import json
import logging
import sys
import traceback

from app.clock import SystemClock


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": getattr(record, "timestamp", SystemClock().now().isoformat()),
            "level": record.levelname,
            "requestId": getattr(record, "request_id", None),
            "path": getattr(record, "path", None),
            "status": getattr(record, "status", None),
            "durationMs": getattr(record, "duration_ms", None),
            "message": record.getMessage(),
        }
        if record.exc_info:
            # Frames only: exception messages, source lines and locals may contain secrets.
            data["stackTrace"] = [
                {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
            data["exceptionType"] = record.exc_info[0].__name__
        return json.dumps(data, ensure_ascii=False)


def configure_logging(level: str) -> logging.Logger:
    logger = logging.getLogger("pickup")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
    return logger
