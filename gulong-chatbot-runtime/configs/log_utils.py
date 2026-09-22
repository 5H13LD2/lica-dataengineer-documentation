"""
log_utils.py
------------

Utility module for project-wide logging with Manila timezone support.

This module defines:
- `ManilaTZFormatter`: A custom logging formatter that forces timestamps
  to Asia/Manila timezone.
- `get_logger`: A helper function to configure and return a logger
  with a Manila-timezone formatter. Ensures consistent formatting across scripts
  while allowing each script to choose its own log level.

Key Features:
-------------
1. **Timezone-aware logging**  
   All timestamps (`%(asctime)s`) are localized to Asia/Manila.

2. **Customizable log levels**  
   Each script can call `get_logger(__name__, level="DEBUG")` (or any other level)
   to control its verbosity. Log levels may be passed as strings
   ("DEBUG", "INFO", "WARNING", etc.) or integers (`logging.DEBUG`).

3. **Keyword-only parameters**  
   Parameters after `*` (e.g., `fmt`, `propagate`) must be passed as
   keywords to avoid accidental misuse.

4. **Clean, consistent format**  
   By default, log messages look like:

    2025-09-03 17:10:25 | INFO | myscript.py:42 | my_function | Something happened

Usage Example:
--------------
```python
from log_utils import get_logger

logger = get_logger(__name__, level="DEBUG")

def process_data():
 logger.info("Starting process")
 try:
     # Your code here
     ...
 except Exception as e:
     logger.error("Process failed: %s", e)

process_data()

Output:
2025-09-03 17:12:00 | INFO | myscript.py:10 | process_data | Starting process
2025-09-03 17:12:01 | ERROR | myscript.py:13 | process_data | Process failed: File not found

Notes:

Avoid calling logging.basicConfig in your project once you use this utility.

Messages are printed to stdout/stderr, which will automatically
appear in Google Cloud logs when running on Cloud Run / GCE.

"""

import datetime
import pytz
import logging

manila_tz = pytz.timezone('Asia/Manila')

# Set up logging
class ManilaTZFormatter(logging.Formatter):
    """
    Custom formatter to handle Manila timezone for logging.
    """
    def converter(self, timestamp) -> datetime.datetime:
        dt = datetime.datetime.fromtimestamp(timestamp, manila_tz)
        return dt

    def formatTime(self, record, datefmt=None) -> str:
        dt = self.converter(record.created)
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            s = dt.strftime("%Y-%m-%d %H:%M:%S")
        return s

_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}

def get_logger(
        name: str | None = None,
        level: int | str = "INFO",
        *,
        fmt: str = "%(asctime)s | %(levelname)s | %(filename)s:%(lineno)d | %(funcName)s | %(message)s",
        propagate: bool = False,
    ):
    """
    Return a logger with Manila-timezone formatted output.
    Each caller can choose its own level.

    Args:
        name: Logger name (None = root).
        level: Log level (int or str like "DEBUG").
        fmt: Log line format.
        propagate: Whether to propagate to parent loggers.
        
    Purpose of "*"
    It means: all parameters that come after * must be passed as keyword arguments, not positional arguments.

    Example:
    # in any script
    >> from log_utils import get_logger
    >> logger = get_logger(__name__, "DEBUG", fmt="...", propagate=True)
    >> logger.debug("Debugging details here")
    """
    if isinstance(level, str):
        level = _LEVELS.get(level.upper(), logging.INFO)

    logger = logging.getLogger(name)  # None = root
    logger.setLevel(level)
    logger.propagate = propagate

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(ManilaTZFormatter(fmt))
        logger.addHandler(handler)

    return logger

def now_str():
    """Output a GMT+8 YYYY-MM-DD HH:MM:SS datetime in string format."""
    return datetime.datetime.now(manila_tz).strftime('%Y-%m-%d %H:%M:%S')