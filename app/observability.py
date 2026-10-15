"""Small JSON log formatter so deployments can aggregate request and error events."""
import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record):
        item = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": record.levelname,
                "logger": record.name, "message": record.getMessage()}
        if record.exc_info:
            item["exception"] = self.formatException(record.exc_info)
        return json.dumps(item, ensure_ascii=False)


def configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
