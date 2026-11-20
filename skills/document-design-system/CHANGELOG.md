# Changelog

## 0.3.1

- SHACL-SPARQL constraints run with pyoxigraph (`scripts/dds_lib/oxshacl.py`); Core shapes stay on pyshacl.
  Targets (targetClass with rdfs:subClassOf*, targetNode, targetSubjectsOf, targetObjectsOf), `$this`
  pre-binding, `sh:prefixes`, `sh:deactivated`, severity and `{?var}` message templates are supported.
  `DDS_SHACL_ENGINE=pyshacl` restores the old engine. Test suite: 50 s → 7 s.
- Includes the source-document build (`scripts/build.py`, `dds:children` sources, `materialize`) and typed
  tables (`ontology/table.ttl`, `instances/table-kinds.ttl`, table/section/source shapes) added after 0.1.0.

## 0.1.0

- Initial skill: compose, validate, render, parse, export.
