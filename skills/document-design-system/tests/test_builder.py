import importlib.util

from _util import SKILL, run

LIB = SKILL / "library" / "planning-components.ttl"
GEN = SKILL / "generated" / "build_planning.py"


def test_library_passes_shacl():
    r = run("validate.py", LIB)
    assert r.returncode == 0, r.stdout


def test_generated_builder_is_current(tmp_path):
    out = tmp_path / "build_planning.py"
    assert run("gen_builder.py", LIB, "-o", out).returncode == 0
    assert out.read_text(encoding="utf-8") == GEN.read_text(encoding="utf-8")


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
