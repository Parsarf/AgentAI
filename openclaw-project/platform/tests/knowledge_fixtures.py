"""The knowledge test documents. They live in `agentai_platform/knowledge_samples.py` so that the evaluation set (`agentai_platform/knowledge_eval.py`) can also run on the
server, where the release has no test folder."""
from agentai_platform.knowledge_samples import *  # noqa: F401,F403
from agentai_platform.knowledge_samples import _esc, _zip  # noqa: F401
