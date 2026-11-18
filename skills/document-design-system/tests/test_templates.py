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


# ---------------------------------------------------------------- v0.3.0 deliberation templates
import shutil  # noqa: E402

from rdflib import Graph  # noqa: E402
from rdflib.compare import isomorphic  # noqa: E402

from dds_lib.graph import DDS, PROV, merge  # noqa: E402
from dds_lib.markdown import parse, render  # noqa: E402
from dds_lib.model import documents  # noqa: E402

DELIB = sorted((SKILL / "templates").glob("deliberation-*.ttl"))


def test_six_deliberation_templates_one_per_frame():
    frames = set()
    for ttl in DELIB:
        g = Graph().parse(ttl)
        frames.add(str(g.value(documents(g)[0], DDS.usesFrame)).rsplit("/", 1)[-1])
    assert frames == {f"{n}-v1" for n in ["ProblemFraming", "DecisionQuestion", "AlternativeComparison",
                                          "IndependentCritique", "DeliberationRevision", "DecisionRecord"]}


@pytest.mark.parametrize("ttl", DELIB, ids=lambda p: p.name)
def test_deliberation_template_valid_and_roundtrips(ttl, tmp_path):
    r = run("validate.py", ttl)
    assert r.returncode == 0, r.stdout + r.stderr
    g0 = Graph().parse(ttl)
    doc = documents(g0)[0]
    g1, _ = parse(render(merge(g0), doc))
    assert isomorphic(g0, g1)
    copy = tmp_path / "doc.ttl"
    copy.write_text(ttl.read_text(encoding="utf-8").replace("new-doc", "my-id"), encoding="utf-8")
    assert run("validate.py", copy).returncode == 0


def test_deliberation_templates_form_a_provenance_chain():
    docs = {}
    for ttl in DELIB:
        g = Graph().parse(ttl)
        d = documents(g)[0]
        docs[d] = set(g.objects(d, PROV.wasDerivedFrom))
    chain = sorted(docs, key=str)
    assert docs[chain[0]] == set()
    for prev, cur in zip(chain, chain[1:]):
        assert docs[cur] == {prev}


def test_deliberation_templates_are_current(tmp_path):
    work = tmp_path / "skill"
    shutil.copytree(SKILL / "templates", work / "templates")
    shutil.copytree(SKILL / "generated", work / "generated")
    import subprocess
    import sys
    subprocess.run([sys.executable, str(work / "templates" / "build_deliberation_templates.py")],
                   check=True, capture_output=True)
    for ttl in DELIB:
        assert (work / "templates" / ttl.name).read_text(encoding="utf-8") == ttl.read_text(encoding="utf-8"), ttl.name
