import os
from pathlib import Path


def _load_dotenv() -> None:
    """Load key=value pairs from .env into os.environ, without overriding
    variables already set by the shell/CI. No external dependency needed:
    the file format used by .env.example is a plain KEY=VALUE list.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()
