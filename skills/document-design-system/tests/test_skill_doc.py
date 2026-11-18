"""SKILL.md is what agents follow: its example must run and its commands must exist."""
import re
import sys
import textwrap

from _util import SKILL, SCRIPTS, run


def test_skill_example_builds_a_valid_document(tmp_path):
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    code = textwrap.dedent(re.search(r"```python\n(.*?)\s*```", text, re.S).group(1))
    code = code.replace('"…"', '"내용"').replace('/abs/path/pilot.ttl', str(tmp_path / "pilot.ttl"))
    sys.path.insert(0, str(SKILL / "generated"))
    ns = {}
    exec("from build_deliberation import Doc\n" + code, ns)
    r = run("validate.py", tmp_path / "pilot.ttl")
    assert r.returncode == 0, r.stdout


def test_skill_mentions_only_existing_scripts():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for name in set(re.findall(r"scripts/([a-z_]+\.py)", text)):
        assert (SCRIPTS / name).exists(), name


def test_state_dir_is_created(tmp_path):
    from _util import FIXTURES
    state = tmp_path / ".dds" / "search-tool-decision"
    r = run("semantic_eval.py", FIXTURES / "valid" / "decision-record.ttl", "--backend", "scripted",
            "--cache", state / "cache.ttl", "--out", state / "assessments.ttl", "--metrics", state / "runs.jsonl")
    assert r.returncode == 0, r.stderr
    assert (state / "cache.ttl").exists() and (state / "runs.jsonl").exists()


def test_readme_example_builds_a_valid_document(tmp_path, monkeypatch):
    text = (SKILL.parents[1] / "README.md").read_text(encoding="utf-8")
    code = re.findall(r"```python\n(.*?)```", text, re.S)[0].replace("/tmp/pilot.ttl", str(tmp_path / "pilot.ttl"))
    monkeypatch.chdir(SKILL)
    exec(code, {})
    assert run("validate.py", tmp_path / "pilot.ttl").returncode == 0
    r = run("evaluate.py", tmp_path / "pilot.ttl")
    assert r.returncode == 0 and "Order: Pass" in r.stdout


def test_readme_mentions_only_existing_scripts():
    text = (SKILL.parents[1] / "README.md").read_text(encoding="utf-8")
    for name in set(re.findall(r"scripts/([a-z_]+\.py)", text)):
        assert (SCRIPTS / name).exists(), name
