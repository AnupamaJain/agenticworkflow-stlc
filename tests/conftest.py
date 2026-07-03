"""
Shared pytest fixtures/setup. Adds `src/` and the project root to sys.path so
tests can `import agents.x`, `import models.state`, `import tools.mcp_client`,
and `import langgraph_agent.graph` without needing the package installed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
