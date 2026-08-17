from functools import lru_cache
from pathlib import Path

ROLE_PROMPT_PATH = Path(__file__).parent / "prompts" / "data_analyst_role.md"


@lru_cache(maxsize=1)
def load_role_prompt() -> str:
    """Load the Advanced AI Data Analyst system prompt used to drive DataMind's agent."""
    return ROLE_PROMPT_PATH.read_text(encoding="utf-8")
