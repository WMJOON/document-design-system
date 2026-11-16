import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROPOSAL = FIXTURES / "valid" / "ai-support-proposal.ttl"
EXAMPLE = SKILL / "instances" / "example-document.ttl"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def run(script: str, *args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd)
