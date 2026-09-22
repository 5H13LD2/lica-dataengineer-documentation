"""
Environment Loader Utility

Loads environment variables from a local `.env` (next to this file) using
`python-dotenv`, and merges them with the current process env.
- Real environment variables take precedence over .env values.
- No working-directory changes; all paths are explicit and stable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from dotenv import dotenv_values, load_dotenv

from configs.log_utils import get_logger

# Fallback to __name__ so notebooks/REPLs without __file__ still work
LOGGER_NAME = __file__ if "__file__" in globals() else __name__
logger = get_logger(LOGGER_NAME, level="INFO")

# Avoid repeating env source logs on repeated imports/reloads
_ENV_LOGGED = False

# Path to the folder containing this file, i.e., .../core
CORE_DIR = Path('configs')
ENV_PATH = CORE_DIR / ".env"

# Load into process env for libraries that read os.environ directly.
# override=False ⇒ real environment vars win over .env (good for Cloud Run).
load_dotenv(ENV_PATH, override=False)


def load_environment_from_file(env_path: Path = ENV_PATH) -> Dict[str, str]:
    """
    Load key/value pairs from the .env file (if present).

    Returns:
        Dict[str, str]: Variables from .env with None values removed. Empty dict if missing.
    """
    global _ENV_LOGGED
    if env_path.exists():
        raw = dotenv_values(env_path)
        # Filter out keys with None values to keep a clean mapping
        env_vars = {k: v for k, v in raw.items() if v is not None}
        if not _ENV_LOGGED:
            logger.info("Loaded .env from %s with %d keys", env_path, len(env_vars))
        return env_vars
    else:
        if not _ENV_LOGGED:
            logger.info("No .env found at %s (using process env only)", env_path)
        return {}

def load_environment():
    """
    Load environment variables with a fallback mechanism.

    Returns:
        Dict[str, str]: Environment variables from `.env` if available, 
        otherwise from system environment (`os.environ`).

    Logic:
        - Attempt to load from `.env` using `load_environment_from_file`.
        - If `.env` is missing, fallback to `os.environ`.

    Example:
        >>> env = load_environment()
        >>> env.get("PATH") is not None
        True
    """
    global _ENV_LOGGED
    env_from_file = load_environment_from_file()
    merged = dict(env_from_file or {})
    # Always layer real process env on top (Cloud Run secrets win).
    merged.update(os.environ)
    if not _ENV_LOGGED:
        if not env_from_file:
            logger.warning("Falling back to system environment variables")
            merged["ENV_SOURCE"] = "process"
        else:
            merged["ENV_SOURCE"] = "both" if os.environ else "dotenv"
        _ENV_LOGGED = True
    return merged

# Create a singleton instance of environment variables
ENV = load_environment()
