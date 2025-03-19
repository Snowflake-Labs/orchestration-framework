from agent_gateway.tools.utils import _should_instrument
from agent_gateway.gateway.gateway import Agent

__all__ = ["Agent", "TruAgent"]


def __getattr__(name):
    if name == "TruAgent":
        if not _should_instrument():
            raise ImportError(
                "TruAgent requires trulens and trulens_connectors_snowflake. "
                "Install with: pip install trulens>=1.4.5 trulens-connectors-snowflake"
            )
        from agent_gateway.gateway.gateway import TruAgent

        return TruAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
