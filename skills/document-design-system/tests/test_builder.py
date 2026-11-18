import importlib.util

import pytest

from _util import SKILL, run

LIB = SKILL / "library" / "planning-components.ttl"
GEN = SKILL / "generated" / "build_planning.py"


def test_library_passes_shacl():
    r = run("validate.py", LIB)
    assert r.returncode == 0, r.stdout


DLIB = SKILL / "library" / "deliberation-components.ttl"
DGEN = SKILL / "generated" / "build_deliberation.py"


@pytest.mark.parametrize("lib,gen", [(LIB, GEN), (DLIB, DGEN)], ids=["planning", "deliberation"])
def test_generated_builder_is_current(lib, gen, tmp_path):
    assert run("validate.py", lib).returncode == 0
    out = tmp_path / gen.name
    assert run("gen_builder.py", lib, "-o", out).returncode == 0
    assert out.read_text(encoding="utf-8") == gen.read_text(encoding="utf-8")


def _load(gen):
    spec = importlib.util.spec_from_file_location(gen.stem, gen)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_links_resolve_forward_and_reject_unknown(tmp_path):
    m = _load(DGEN)
    d = m.Doc("t", "제목", frame="IndependentCritique-v1")
    d.add(d.critique("cr", "지적", targets=["cl"], resolution="accepted"),  # forward reference
          d.claim("cl", "주장"))
    ttl = tmp_path / "t.ttl"
    d.write(ttl)
    assert run("validate.py", ttl).returncode == 0
    bad = m.Doc("t", "제목")
    bad.add(bad.claim("cl", "주장", supportedBy=["nope"]))
    with pytest.raises(ValueError, match="unknown component id"):
        bad.write()
    with pytest.raises(ValueError, match="unknown link"):
        m.Node("x", "Paragraph", links={"dependsOn": ["cl"]})


def test_built_document_validates_and_renders(tmp_path):
    spec = importlib.util.spec_from_file_location("build_planning", GEN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    d = m.Doc("t", "제목")
    d.add(d.section("s", d.heading("s-h", "개요"), d.requirement("REQ1", "해야 한다"),
                    d.bullet_list("l", d.constraint_item("C1", "제약"), "평문"),
                    d.table("t1", ["a", "b"], d.table_row("t1-r2", "x", d.decision_cell("dc", "y")))))
    ttl = tmp_path / "t.ttl"
    d.write(ttl)
    assert run("validate.py", ttl).returncode == 0
    assert run("render.py", ttl, "-o", tmp_path / "t.md").returncode == 0


def test_duplicate_id_rejected(tmp_path):
    spec = importlib.util.spec_from_file_location("build_planning", GEN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    d = m.Doc("t", "제목")
    d.add(d.heading("x", "a"), d.heading("x", "b"))
    try:
        d.write()
    except ValueError as e:
        assert "duplicate" in str(e)
    else:
        raise AssertionError("expected ValueError")
