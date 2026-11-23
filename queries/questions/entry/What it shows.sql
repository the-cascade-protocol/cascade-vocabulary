-- part: prepare
-- The statements the views make, a view's entries and the nodes named after them as the derived state names them,
-- each view's in a statement of its own, which a runtime's SQLite nests deeper than it would the twelve in one.
DROP TABLE IF EXISTS temp.view_statements;
CREATE TEMP TABLE view_statements (address TEXT, s TEXT, p TEXT, o TEXT) STRICT;
INSERT INTO view_statements SELECT k.address, x.s, x.p, x.o FROM allergy_terms k CROSS JOIN allergy_triples x;
INSERT INTO view_statements SELECT k.address, x.s, x.p, x.o FROM condition_terms k CROSS JOIN condition_triples x;
INSERT INTO view_statements SELECT k.address, x.s, x.p, x.o FROM immunization_terms k CROSS JOIN immunization_triples x;
INSERT INTO view_statements SELECT k.address, x.s, x.p, x.o FROM lab_result_terms k CROSS JOIN lab_result_triples x;
INSERT INTO view_statements SELECT k.address, x.s, x.p, x.o FROM medication_dispense_terms k CROSS JOIN medication_dispense_triples x;
INSERT INTO view_statements SELECT k.address, x.s, x.p, x.o FROM medication_terms k CROSS JOIN medication_triples x;
INSERT INTO view_statements SELECT k.address, x.s, x.p, x.o FROM note_terms k CROSS JOIN note_triples x;
INSERT INTO view_statements SELECT k.address, x.s, x.p, x.o FROM patient_profile_terms k CROSS JOIN patient_profile_triples x;
INSERT INTO view_statements SELECT k.address, x.s, x.p, x.o FROM procedure_terms k CROSS JOIN procedure_triples x;
INSERT INTO view_statements SELECT k.address, x.s, x.p, x.o FROM report_terms k CROSS JOIN report_triples x;
INSERT INTO view_statements SELECT k.address, x.s, x.p, x.o FROM variant_interpretation_terms k CROSS JOIN variant_interpretation_triples x;
INSERT INTO view_statements SELECT k.address, x.s, x.p, x.o FROM variant_terms k CROSS JOIN variant_triples x;
CREATE INDEX temp.view_statements_p ON view_statements (p);
CREATE INDEX temp.view_statements_s ON view_statements (s);
ANALYZE temp.view_statements;
-- part: answer
WITH
  entries (address, entry) AS MATERIALIZED (SELECT DISTINCT address, s FROM view_statements WHERE p = '<https://ns.cascadeprotocol.org/cascade#entryMember>'),
  leaders (entry, leader) AS MATERIALIZED (SELECT s, o FROM view_statements WHERE p = '<https://ns.cascadeprotocol.org/cascade#leadMember>'),
  currents (entry, node) AS MATERIALIZED (SELECT s, o FROM view_statements WHERE p = '<https://ns.cascadeprotocol.org/cascade#memberCurrentValues>'),
  owners (node, member) AS MATERIALIZED (SELECT s, o FROM view_statements WHERE p = '<https://ns.cascadeprotocol.org/cascade#valuesOfMember>'),
  -- Every value a member's current values state, in the entry whose lead and node they are.
  of_members (address, entry, field, value, from_member, lead) AS MATERIALIZED (
    SELECT DISTINCT en.address, en.entry, f.p, f.o, ow.member, CASE WHEN ow.member = ld.leader THEN 1 ELSE 0 END
    FROM view_statements f CROSS JOIN owners ow ON ow.node = f.s
    CROSS JOIN currents cu ON cu.node = f.s
    CROSS JOIN leaders ld ON ld.entry = cu.entry
    CROSS JOIN entries en ON en.entry = cu.entry
    WHERE f.p NOT IN ('<https://ns.cascadeprotocol.org/cascade#valuesOfMember>', '<https://ns.cascadeprotocol.org/cascade#paddedDateTime>', '<https://ns.cascadeprotocol.org/cascade#referenceRangeLow>', '<https://ns.cascadeprotocol.org/cascade#referenceRangeHigh>')),
  -- Every value an entry states that none of its members' current values states too.
  of_entries (address, entry, field, value, from_member, lead) AS (
    SELECT DISTINCT en.address, en.entry, f.p, f.o, NULL, NULL
    FROM view_statements f CROSS JOIN entries en ON en.entry = f.s
    WHERE f.p NOT IN ('<https://ns.cascadeprotocol.org/cascade#memberCurrentValues>', '<https://ns.cascadeprotocol.org/cascade#paddedDateTime>', '<https://ns.cascadeprotocol.org/cascade#referenceRangeLow>', '<https://ns.cascadeprotocol.org/cascade#referenceRangeHigh>')
      AND NOT EXISTS (SELECT 1 FROM of_members m WHERE m.entry = f.s AND m.field = f.p AND m.value = f.o)),
  -- An entry is named under the address of the view that gives it members, wherever another view names it.
  said (address, entry, field, value, from_member, lead) AS (
    SELECT DISTINCT s.address, '<' || s.address || '#' || substr(s.entry, 20), s.field,
      CASE WHEN substr(s.value, 1, 19) = '<urn:cascade:entry:'
           THEN '<' || coalesce((SELECT o.address FROM entries o WHERE o.entry = s.value), s.address) || '#' || substr(s.value, 20)
           ELSE s.value END,
      s.from_member, s.lead
    FROM (SELECT * FROM of_members UNION SELECT * FROM of_entries) s),
  entry_labels (entry, label) AS (SELECT entry, label FROM shown_in_entry),
  labelled (address, entry, entry_label, field, value, value_label, from_member, from_label, lead) AS (
    SELECT DISTINCT said.address, said.entry, el.label, said.field, said.value, vl.o, said.from_member, fl.o, said.lead
    FROM said LEFT JOIN entry_labels el ON el.entry = said.entry
    LEFT JOIN term vt ON vt.nt = said.value
    LEFT JOIN quad vl ON vl.s = vt.id AND vl.p = (SELECT id FROM term WHERE nt = '<http://www.w3.org/2000/01/rdf-schema#label>')
    LEFT JOIN term ft ON ft.nt = said.from_member
    LEFT JOIN quad fl ON fl.s = ft.id AND fl.p = (SELECT id FROM term WHERE nt = '<http://www.w3.org/2000/01/rdf-schema#label>'))
SELECT labelled.entry AS entry, entry_label.nt AS entryLabel, '<' || labelled.address || '>' AS view,
  labelled.field AS field, labelled.value AS value, value_label.nt AS valueLabel, labelled.from_member AS "from",
  from_label.nt AS fromLabel,
  CASE labelled.lead WHEN 1 THEN '"true"^^<http://www.w3.org/2001/XMLSchema#boolean>'
    WHEN 0 THEN '"false"^^<http://www.w3.org/2001/XMLSchema#boolean>' END AS lead
FROM labelled LEFT JOIN term entry_label ON entry_label.id = labelled.entry_label
LEFT JOIN term value_label ON value_label.id = labelled.value_label
LEFT JOIN term from_label ON from_label.id = labelled.from_label
ORDER BY entry_label.kind, entry_label.lex, substr(labelled.entry, 2, length(labelled.entry) - 2),
  substr(labelled.field, 2, length(labelled.field) - 2), labelled.lead DESC,
  CASE WHEN substr(labelled.value, 1, 1) = '<' THEN substr(labelled.value, 2, length(labelled.value) - 2)
       ELSE (SELECT lex FROM term WHERE nt = labelled.value) END,
  substr(labelled.from_member, 2, length(labelled.from_member) - 2)
-- part: cleanup
DROP TABLE IF EXISTS temp.view_statements;
