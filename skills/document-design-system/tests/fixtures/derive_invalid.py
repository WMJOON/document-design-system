#!/usr/bin/env python3
"""Derive single-violation invalid fixtures from valid/decision-record.ttl.

Run from tests/fixtures after editing the valid fixture: python3 derive_invalid.py
Each mutation must remove or break exactly one thing (see tests/test_validation.py::EXPECT).
"""
base=open("valid/decision-record.ttl").read()
MARK="# Fictional decision record (DecisionRecord-v1)."
def mut(name, note, *pairs):
    s=base
    for old,new in pairs:
        assert s.count(old)==1,(name,old); s=s.replace(old,new)
    s=s.replace(MARK, f"# INVALID ({name}): {note}\n# Derived from valid/decision-record.ttl.\n"+MARK,1)
    open(f"invalid/{name}.ttl","w").write(s)
mut("frame-requirement-unmet","DecisionRecord-v1 requires a Rationale component; it was relabelled Description.",
    ("dds:hasSemantic semantic:Rationale ;","dds:hasSemantic semantic:Description ;"))
mut("elaboration-not-deeper","Overview elaboratedBy points to a sibling, not into a deeper Section.",
    ("dds:elaboratedBy c:decision , c:claim ;","dds:elaboratedBy c:question ;"))
mut("premise-after-dependent","Decision depends on (basedOn) a premise placed after it.",
    ("dds:basedOn c:scope , c:criterion ;","dds:basedOn c:scope , c:criterion-rev ;"))
mut("revision-before-original","A premise revision (prov:wasRevisionOf) is placed before the premise it revises.",
    ("dds:hasSemantic semantic:Criterion ; prov:wasRevisionOf c:criterion ;","dds:hasSemantic semantic:Criterion ;"),
    ("dds:hasSemantic semantic:Scope ;","dds:hasSemantic semantic:Scope ; prov:wasRevisionOf c:criterion-rev ;"))
mut("counter-without-target","Counterargument has no dds:counters.",
    ("dds:hasSemantic semantic:Counterargument ; dds:counters c:claim ;","dds:hasSemantic semantic:Counterargument ;"))
mut("critique-without-resolution","Critique has no dds:resolution.",
    (" ; dds:resolution resolution:deferred ;"," ;"))
mut("critique-without-target","Critique has no dds:targets.",
    ("dds:hasSemantic semantic:Critique ; dds:targets c:criterion ;","dds:hasSemantic semantic:Critique ;"))
mut("deferred-critique-unlinked","Deferred critique is not carried by an UnresolvedIssue.",
    ("dds:hasSemantic semantic:UnresolvedIssue ; prov:wasDerivedFrom c:critique ;","dds:hasSemantic semantic:UnresolvedIssue ;"))
mut("traceability-missing","DecisionRecord-v1 requires traceability; the Decision has no dds:supportedBy.",
    ("dds:basedOn c:scope , c:criterion ; dds:supportedBy c:rationale ;","dds:basedOn c:scope , c:criterion ;"))
mut("multiple-frames","Document uses two Frames.",
    ("dds:usesFrame frame:DecisionRecord-v1 ;","dds:usesFrame frame:DecisionRecord-v1 , frame:IndependentCritique-v1 ;"))
mut("invalid-resolution","dds:resolution is a literal, not a resolution concept.",
    ("dds:resolution resolution:deferred ;",'dds:resolution "deferred" ;'))
mut("provenance-literal","prov:hadPrimarySource is a literal, not an IRI.",
    ("prov:hadPrimarySource <https://example.org/sources/pilot-survey> ;",'prov:hadPrimarySource "pilot survey" ;'))
mut("relation-untyped-target","dds:supportedBy points to a node that is not a component.",
    ("dds:hasSemantic semantic:Claim ; dds:supportedBy c:evidence ;","dds:hasSemantic semantic:Claim ; dds:supportedBy c:missing-evidence ;"))
