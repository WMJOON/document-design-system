from _util import EXAMPLE, SKILL  # noqa: F401  (sets sys.path)

from rdflib import Graph
from rdflib.namespace import OWL, RDF, RDFS

from dds_lib.graph import DDS, load_data, load_shapes, load_tbox, validate_graph

TOP = ["Document", "DesignSystem", "Component", "Structure", "Semantic", "Presentation", "PresentationBinding"]
SUB = {
    "Structure": ["Section", "Heading", "Paragraph", "List", "ListItem", "Table", "TableRow", "TableCell"],
    "Semantic": ["Requirement", "Policy", "Constraint", "Decision", "Evidence", "Assumption", "Description"],
    "Presentation": ["Typography", "Layout", "Style"],
}
OBJ_PROPS = ["usesDesignSystem", "hasComponent", "supportsStructure", "supportsSemantic", "supportsPresentation",
             "hasDefaultPresentation", "forStructure", "presentation", "hasStructure", "hasSemantic",
             "hasPresentation", "hasChild"]
DATA_PROPS = ["hasOrder", "hasContent", "ordered", "token"]


def test_each_ontology_file_parses():
    for f in sorted((SKILL / "ontology").glob("*.ttl")):
        assert len(Graph().parse(f)) > 0, f


def test_shapes_parse():
    assert len(load_shapes()) > 0


def test_classes_and_properties_declared():
    g = load_tbox()
    for c in TOP:
        assert (DDS[c], RDF.type, OWL.Class) in g, c
    for parent, subs in SUB.items():
        for s in subs:
            assert (DDS[s], RDFS.subClassOf, DDS[parent]) in g, s
    for p in OBJ_PROPS:
        assert (DDS[p], RDF.type, OWL.ObjectProperty) in g, p
    for p in DATA_PROPS:
        assert (DDS[p], RDF.type, OWL.DatatypeProperty) in g, p


def test_only_approved_top_level_classes():
    g = load_tbox()
    classes = set(g.subjects(RDF.type, OWL.Class))
    top = {c for c in classes if not set(g.objects(c, RDFS.subClassOf))}
    assert top == {DDS[c] for c in TOP}


def test_no_punning_in_abox():
    """ABox individuals must not reuse TBox class IRIs (no OWL punning)."""
    classes = set(load_tbox().subjects(RDF.type, OWL.Class))
    abox = Graph().parse(SKILL / "instances" / "design-system.ttl").parse(EXAMPLE)
    subjects = set(abox.subjects())
    assert not (subjects & classes)


def test_example_document_conforms():
    r = validate_graph(load_data([EXAMPLE]))
    assert r.conforms, r.violations
