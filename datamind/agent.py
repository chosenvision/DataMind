import os
from pathlib import Path

from google import genai
from google.genai import types

from datamind.config import UserConfig
from datamind.profiler import format_profile_summary, profile_dataset
from datamind.role import load_role_prompt

DEFAULT_MODEL = os.environ.get("DATAMIND_MODEL", "gemini-2.5-flash")
DEFAULT_MAX_TOKENS = 8192


class DataAnalystAgent:
    """Runs the Advanced AI Data Analyst role against a dataset via the Gemini API.

    The role prompt (datamind/prompts/data_analyst_role.md) is used verbatim as the
    system instruction. The dataset is profiled deterministically first (see
    datamind.profiler) so the model works from verified facts about shape, dtypes,
    missingness, and distributions rather than re-deriving them, then produces the
    full analysis, dashboard specification, and recommendations described by the role.

    Uses Gemini (rather than a paid-only API) so the free tier of a Google AI Studio
    API key is enough to run this end to end with no billing setup.
    """

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL) -> None:
        self.client = genai.Client(api_key=api_key) if api_key else genai.Client()
        self.model = model
        self.system_prompt = load_role_prompt()

    def build_user_message(
        self,
        dataset_path: str | Path,
        config: UserConfig | None = None,
        question: str | None = None,
    ) -> str:
        config = config or UserConfig()
        profile = profile_dataset(dataset_path)
        sections = [config.to_brief(), format_profile_summary(profile)]
        if question:
            sections.append(f"# SPECIFIC QUESTION\n{question}")
        sections.append(
            "Proceed autonomously through the full workflow defined in your role "
            "instructions and produce the Final Deliverable."
        )
        return "\n\n".join(sections)

    def analyze(
        self,
        dataset_path: str | Path,
        config: UserConfig | None = None,
        question: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        user_message = self.build_user_message(dataset_path, config, question)
        response = self.client.models.generate_content(
            model=self.model,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                max_output_tokens=max_tokens,
            ),
        )
        return response.text
