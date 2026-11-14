"""
The two Groq models the app uses.

  fast_llm  — small and quick: sentiment/intent classification, summaries
  agent_llm — stronger: the tool-calling agent that talks to the caller
"""
from langchain_groq import ChatGroq
from pydantic import SecretStr
from app.config import get_settings

settings = get_settings()


def _make(model: str, temperature: float) -> ChatGroq:
    kwargs = {}
    # reasoning_effort is only accepted by reasoning models
    if settings.llm_reasoning_effort and model.startswith("openai/gpt-oss"):
        kwargs["reasoning_effort"] = settings.llm_reasoning_effort
    return ChatGroq(
        api_key=SecretStr(settings.groq_api_key),
        model=model,
        temperature=temperature,
        max_retries=1,
        **kwargs,
    )


fast_llm = _make(settings.llm_model, 0.0)
agent_llm = _make(settings.agent_model, settings.llm_temperature)
