import pytest

from _util import SKILL, run

TEMPLATES = sorted((SKILL / "templates").glob("default-*.ttl"))


@pytest.mark.parametrize("ttl", TEMPLATES, ids=lambda p: p.name)
def test_default_template_passes_shacl_and_renders(ttl, tmp_path):
    r = run("validate.py", ttl)
    assert r.returncode == 0, r.stdout + r.stderr
    assert run("render.py", ttl, "-o", tmp_path / "doc.md").returncode == 0


@pytest.mark.parametrize("ttl", TEMPLATES, ids=lambda p: p.name)
def test_renamed_copy_stays_valid(ttl, tmp_path):
    copy = tmp_path / "doc.ttl"
    copy.write_text(ttl.read_text(encoding="utf-8").replace("new-doc", "my-id"), encoding="utf-8")
    assert run("validate.py", copy).returncode == 0
