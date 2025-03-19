from agent_gateway.tools.utils import _should_instrument
from agent_gateway.gateway.gateway import Agent

__all__ = ["Agent", "TruAgent"]

if _should_instrument():
    from agent_gateway.gateway.gateway import TruAgent
else:
    raise ImportError(
        "TruAgent requires trulens and trulens_connectors_snowflake. "
        "Please install these packages to use TruAgent."
    )
