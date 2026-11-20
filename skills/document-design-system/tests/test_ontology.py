from _util import EXAMPLE, SKILL  # noqa: F401  (sets sys.path)

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from dds_lib.graph import DDS, load_data, load_shapes, load_tbox, validate_graph

TOP = ["Document", "DesignSystem", "Component", "Structure", "Semantic", "Presentation", "PresentationBinding",
       # v0.3.0, approved by the user (DDS work-memory UD-01a1ee9790e7)
       "DocumentFrame", "FrameRequirement", "SemanticBinding"]
SUB = {
    "Structure": ["Section", "Heading", "Paragraph", "List", "ListItem", "Table", "TableRow", "TableCell"],
    "Semantic": ["Requirement", "Policy", "Constraint", "Decision", "Evidence", "Assumption", "Description",
                 "Problem", "Goal", "Scope", "DecisionQuestion", "Criterion", "Alternative", "Claim",
                 "Counterargument", "Perspective", "Risk", "Rationale", "Critique", "UnresolvedIssue"],
    "Presentation": ["Typography", "Layout", "Style"],
}
OBJ_PROPS = ["usesDesignSystem", "hasComponent", "supportsStructure", "supportsSemantic", "supportsPresentation",
             "hasDefaultPresentation", "forStructure", "presentation", "hasStructure", "hasSemantic",
             "hasPresentation", "hasChild",
             "usesFrame", "hasRequirement", "definesPresentationMapping", "compatibleDesignSystem",
             "requiredSemantic", "forSemantic", "mappedPresentation", "relatesTo", "elaboratedBy",
             "supportedBy", "basedOn", "counters", "targets", "resolution"]
DATA_PROPS = ["hasOrder", "hasContent", "ordered", "token", "requiresTraceability", "frameQuestion", "minOccurs"]


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
    abox = (Graph().parse(SKILL / "instances" / "design-system.ttl")
            .parse(SKILL / "instances" / "frames.ttl").parse(EXAMPLE))
    subjects = set(abox.subjects())
    assert not (subjects & classes)


def test_example_document_conforms():
    r = validate_graph(load_data([EXAMPLE]))
    assert r.conforms, r.violations


def test_ontology_version():
    g = load_tbox()
    assert (URIRef("https://example.org/ontology/dds"), OWL.versionInfo, Literal("0.3.1")) in g


# The v0.2.0 DesignSystem contract must not change (v0.3.0 adds DeliberationSystem instead).
V02_DS = {
    "PlanningSystem": {
        "supportsStructure": {"Section", "Heading", "Paragraph", "List", "ListItem", "Table", "TableRow", "TableCell"},
        "supportsSemantic": {"Requirement", "Policy", "Constraint", "Decision", "Evidence", "Assumption", "Description"},
        "supportsPresentation": {"Heading1", "Heading2", "Body", "Emphasis", "Callout"},
        "hasDefaultPresentation": {"PlanningSystem-Heading", "PlanningSystem-Paragraph"},
    },
    "MemoSystem": {
        "supportsStructure": {"Section", "Heading", "Paragraph"},
        "supportsSemantic": {"Description", "Decision"},
        "supportsPresentation": {"Body"},
        "hasDefaultPresentation": {"MemoSystem-Paragraph"},
    },
}


def test_existing_design_systems_unchanged():
    g = Graph().parse(SKILL / "instances" / "design-system.ttl")
    design = Namespace("https://example.org/data/design/")
    for ds, props in V02_DS.items():
        for p, expected in props.items():
            got = {str(o).rsplit("/", 1)[-1] for o in g.objects(design[ds], DDS[p])}
            assert got == expected, (ds, p)


def test_standard_frames_conform_and_are_versioned():
    from dds_lib.graph import DEFAULT_FRAMES
    g = Graph().parse(DEFAULT_FRAMES)
    frames = set(g.subjects(RDF.type, DDS.DocumentFrame))
    names = {str(f).rsplit("/", 1)[-1] for f in frames}
    assert names == {f"{n}-v1" for n in ["ProblemFraming", "DecisionQuestion", "AlternativeComparison",
                                          "IndependentCritique", "DeliberationRevision", "DecisionRecord"]}
    for f in frames:
        assert g.value(f, OWL.versionInfo) is not None, f
    assert validate_graph(load_data([])).conforms


def test_overview_is_not_a_semantic_type():
    """Overview/summary is the relative role of a Section's leading content (Section depth), not a Semantic."""
    g = load_tbox()
    for name in ("Summary", "Overview"):
        assert (DDS[name], RDF.type, OWL.Class) not in g
