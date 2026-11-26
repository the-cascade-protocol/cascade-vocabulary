-- A list question over the medications screen, paged as queries/statements.sql says.
WITH
  page (entry, iri, sort_key, name, selected, status, lifecycle, started, written, ended, label) AS (
    SELECT m.entry, m.iri, m.sort_key, m.name, m.selected, m.status, m.lifecycle, m.started, m.written, m.ended, m.label
    FROM medication m
    WHERE m.sort_key > coalesce(:after, '')
      AND m.name IS NOT NULL
      AND m.lifecycle = (SELECT id FROM term WHERE nt = '<https://ns.cascadeprotocol.org/cascade#MedicationActive>')
      AND EXISTS (SELECT 1 FROM medication_member r WHERE r.entry = m.entry)
      AND (NOT EXISTS (SELECT 1 FROM asked)
           OR EXISTS (SELECT 1 FROM medication_member r JOIN asked ON asked.term = r.record WHERE r.entry = m.entry))
    ORDER BY m.sort_key
    LIMIT coalesce(:page_size, -1)),
  strings (id, said) AS NOT MATERIALIZED (
    SELECT id, CASE kind WHEN 2 THEN lex WHEN 3 THEN substr(nt, 2, length(nt) - 2 - CASE WHEN lang IS NOT NULL
      THEN length(lang) + 1 WHEN datatype = 'http://www.w3.org/2001/XMLSchema#string' THEN 0
      ELSE length(datatype) + 4 END) END FROM term),
  statuses (entry, line, shown) AS (
    SELECT v.entry, m.lex || ' ' || coalesce(st.lex, 'with no status') || coalesce(', ended ' || en.lex, '') || char(31),
      m.lex || ' ' || coalesce(st_said.said, 'with no status') || coalesce(', ended ' || en_said.said, '')
    FROM medication_member_values v JOIN page ON page.entry = v.entry JOIN term m ON m.id = v.member
    LEFT JOIN term st ON st.id = v.status LEFT JOIN strings st_said ON st_said.id = v.status
    LEFT JOIN term en ON en.id = v.ended LEFT JOIN strings en_said ON en_said.id = v.ended),
  dosages (entry, key, line, shown) AS (
    SELECT v.entry, coalesce(wr.lex, '~'),
      m.lex || ' ' || d.lex || coalesce(', written ' || wr.lex, '') || char(31),
      m.lex || ' ' || d_said.said || coalesce(', written ' || wr_said.said, '')
    FROM medication_member_values v JOIN page ON page.entry = v.entry JOIN term m ON m.id = v.member
    JOIN term d ON d.id = v.dosage JOIN strings d_said ON d_said.id = v.dosage
    LEFT JOIN term wr ON wr.id = v.written LEFT JOIN strings wr_said ON wr_said.id = v.written),
  dosage_routes (entry, member, dosage, k1, k2, part) AS (
    SELECT x.entry, x.member, x.dosage, t.lex, '', ', route ' || t.lex
    FROM medication_member_values_dosage_route x JOIN page ON page.entry = x.entry JOIN term t ON t.id = x.code
    UNION SELECT x.entry, x.member, x.dosage, t.lex, t.datatype, ', route ' || t.datatype || ' ' || s.said
    FROM medication_member_values_dosage_route_other_system x JOIN page ON page.entry = x.entry
    JOIN term t ON t.id = x.code JOIN strings s ON s.id = x.code),
  dosage_bases (entry, member, dosage, number, frequency, period, period_unit, from_id, until_id, dose_written, dose_comparator, dose_unit) AS (
    SELECT d.entry, d.member, d.dosage, d.number, d.frequency, d.period, d.period_unit,
      coalesce((SELECT min(w.written) FROM medication_member_values_dosage_padded w
                WHERE w.entry = d.entry AND w.member = d.member AND w.dosage = d.dosage AND w.property = k.dosage_bounds_period_start),
               d.bounds_start),
      coalesce((SELECT min(w.written) FROM medication_member_values_dosage_padded w
                WHERE w.entry = d.entry AND w.member = d.member AND w.dosage = d.dosage AND w.property = k.dosage_bounds_period_end),
               d.bounds_end),
      d.dose_written, d.dose_comparator, coalesce(d.dose_unit_text, d.dose_ucum)
    FROM medication_terms k CROSS JOIN medication_member_values_dosage d JOIN page ON page.entry = d.entry),
  structured_dosages (entry, member_lex, len, number, shown) AS (
    SELECT b.entry, m.lex, length(b.number), b.number,
      m.lex || ' dosage ' || b.number
      || CASE WHEN b.frequency IS NOT NULL AND b.period IS NOT NULL AND b.period_unit IS NOT NULL
              THEN ', ' || fr.said || ' per ' || pe.said || ' ' || pu.said ELSE '' END
      || CASE WHEN b.frequency IS NOT NULL AND NOT (b.period IS NOT NULL AND b.period_unit IS NOT NULL)
              THEN ', frequency ' || fr.said ELSE '' END
      || CASE WHEN b.period IS NOT NULL AND NOT (b.frequency IS NOT NULL AND b.period_unit IS NOT NULL)
              THEN ', period ' || pe.said || coalesce(' ' || pu.said, '') ELSE '' END
      || CASE WHEN b.period_unit IS NOT NULL AND b.period IS NULL THEN ', period unit ' || pu.said ELSE '' END
      || CASE WHEN b.from_id IS NOT NULL THEN ', from ' || fs.said ELSE '' END
      || CASE WHEN b.until_id IS NOT NULL THEN ', until ' || us.said ELSE '' END
      || coalesce((SELECT group_concat(r.part, '' ORDER BY r.k1, r.k2) FROM dosage_routes r
                   WHERE r.entry = b.entry AND r.member = b.member AND r.dosage = b.dosage), '')
      || CASE WHEN b.dose_written IS NOT NULL
              THEN ', dose ' || coalesce(cs.said, '') || dw.said || coalesce(' ' || ds.said, '') ELSE '' END
    FROM dosage_bases b JOIN term m ON m.id = b.member
    LEFT JOIN strings fr ON fr.id = b.frequency LEFT JOIN strings pe ON pe.id = b.period LEFT JOIN strings pu ON pu.id = b.period_unit
    LEFT JOIN strings fs ON fs.id = b.from_id LEFT JOIN strings us ON us.id = b.until_id
    LEFT JOIN strings dw ON dw.id = b.dose_written LEFT JOIN strings cs ON cs.id = b.dose_comparator
    LEFT JOIN strings ds ON ds.id = b.dose_unit),
  prescription_details (entry, member_lex, shown) AS (
    SELECT entry, member_lex, member_lex || ' ' || substr(parts, 3) FROM (
      SELECT v.entry, m.lex AS member_lex,
        coalesce(', intent ' || ri.said, '') || coalesce(', course ' || co.said, '')
        || coalesce(', dispense request valid from ' || vf.said, '')
        || coalesce(', dispense request valid until ' || vu.said, '') AS parts
      FROM medication_terms k CROSS JOIN medication_member_values v JOIN page ON page.entry = v.entry JOIN term m ON m.id = v.member
      LEFT JOIN strings ri ON ri.id = v.request_intent LEFT JOIN strings co ON co.id = v.course
      LEFT JOIN strings vf ON vf.id = coalesce((SELECT min(w.written) FROM medication_member_values_padded w
                                                WHERE w.entry = v.entry AND w.member = v.member
                                                  AND w.property = k.dispense_request_validity_period_start), v.validity_start)
      LEFT JOIN strings vu ON vu.id = coalesce((SELECT min(w.written) FROM medication_member_values_padded w
                                                WHERE w.entry = v.entry AND w.member = v.member
                                                  AND w.property = k.dispense_request_validity_period_end), v.validity_end))
    WHERE parts <> ''),
  said (entry, line, shown) AS (
    SELECT v.entry, m.lex || ' ' || n.lex || char(31), m.lex || ' ' || n_said.said
    FROM medication_member_values v JOIN page ON page.entry = v.entry JOIN term m ON m.id = v.member
    JOIN term n ON n.id = v.narrative JOIN strings n_said ON n_said.id = v.narrative),
  reasons (entry, k1, k2, member, line, shown) AS (
    SELECT DISTINCT v.entry, coalesce(cn.lex, ''), substr(c.iri, 2, length(c.iri) - 2), m.lex,
      m.lex || ' for ' || substr(c.iri, 2, length(c.iri) - 2) || coalesce(', ' || cn.lex, '') || char(31),
      m.lex || ' for ' || substr(c.iri, 2, length(c.iri) - 2) || coalesce(', ' || CASE cn.kind WHEN 2 THEN cn.lex WHEN 3 THEN substr(cn.nt, 2, length(cn.nt) - 2 - CASE WHEN cn.lang IS NOT NULL
        THEN length(cn.lang) + 1 WHEN cn.datatype = 'http://www.w3.org/2001/XMLSchema#string' THEN 0
        ELSE length(cn.datatype) + 4 END) END, '')
    FROM page CROSS JOIN medication_member_values_reason_condition v ON v.entry = page.entry JOIN term m ON m.id = v.member
    JOIN condition_member cm ON cm.record = v.record JOIN condition c ON c.entry = cm.entry
    LEFT JOIN term cn ON cn.id = c.name
    UNION SELECT v.entry, code.lex, '', m.lex, m.lex || ' for ' || code.lex || char(31), m.lex || ' for ' || CASE code.kind WHEN 2 THEN code.lex WHEN 3 THEN substr(code.nt, 2, length(code.nt) - 2 - CASE WHEN code.lang IS NOT NULL
        THEN length(code.lang) + 1 WHEN code.datatype = 'http://www.w3.org/2001/XMLSchema#string' THEN 0
        ELSE length(code.datatype) + 4 END) END
    FROM page CROSS JOIN medication_member_values_reason_code v ON v.entry = page.entry JOIN term m ON m.id = v.member
    JOIN term code ON code.id = v.code
    UNION SELECT v.entry, code.lex, code.datatype, m.lex,
      m.lex || ' for ' || code.datatype || ' ' || code.lex || char(31),
      m.lex || ' for ' || code.datatype || ' ' || CASE code.kind WHEN 2 THEN code.lex WHEN 3 THEN substr(code.nt, 2, length(code.nt) - 2 - CASE WHEN code.lang IS NOT NULL
        THEN length(code.lang) + 1 WHEN code.datatype = 'http://www.w3.org/2001/XMLSchema#string' THEN 0
        ELSE length(code.datatype) + 4 END) END
    FROM page CROSS JOIN medication_member_values_reason_other_system v ON v.entry = page.entry
    JOIN term m ON m.id = v.member JOIN term code ON code.id = v.code),
  candidates (entry, n, only) AS (
    SELECT entry, count(DISTINCT nt), min(nt) FROM (
      SELECT c.entry, CASE t.kind WHEN 2 THEN t.nt ELSE '<https://ns.cascadeprotocol.org/codes/rxnorm/' || sparql_encode_for_uri(t.lex) || '>' END AS nt
      FROM page CROSS JOIN medication_code c ON c.entry = page.entry JOIN term t ON t.id = c.code WHERE t.kind IN (2, 3))
    GROUP BY entry)
SELECT name.nt AS medication,
  coalesce(CASE WHEN instr(chosen.lex, 'https://ns.cascadeprotocol.org/codes/rxnorm/') = 1 THEN chosen.nt END,
           CASE WHEN candidates.n = 1 THEN candidates.only END) AS code,
  started.nt AS started, written.nt AS written,
  (SELECT '"' || group_concat(s.shown, '' ORDER BY s.line) || '"' FROM statuses s WHERE s.entry = page.entry)
    AS statuses,
  (SELECT '"' || group_concat(s.shown, '' ORDER BY s.key, s.line) || '"' FROM dosages s WHERE s.entry = page.entry)
    AS dosages,
  (SELECT '"' || group_concat(s.shown, char(31) ORDER BY s.member_lex, s.len, s.number) || '"' FROM structured_dosages s WHERE s.entry = page.entry)
    AS structuredDosages,
  (SELECT '"' || group_concat(s.shown, char(31) ORDER BY s.member_lex) || '"' FROM prescription_details s WHERE s.entry = page.entry)
    AS prescriptionDetails,
  (SELECT '"' || group_concat(s.shown, '' ORDER BY s.line) || '"' FROM said s WHERE s.entry = page.entry)
    AS narrativeTexts,
  (SELECT '"' || group_concat(s.shown, '' ORDER BY s.k1, s.k2, s.member, s.line) || '"'
   FROM reasons s WHERE s.entry = page.entry) AS reasons,
  '"' || (SELECT count(*) FROM medication_member m WHERE m.entry = page.entry
          AND (NOT EXISTS (SELECT 1 FROM asked) OR m.record IN (SELECT term FROM asked)))
    || '"^^<http://www.w3.org/2001/XMLSchema#integer>' AS records,
  page.iri AS entry, label.nt AS entryLabel,
  (SELECT '"' || group_concat(s.shown, '' ORDER BY s.line) || '"'
   FROM medication_source s WHERE s.entry = page.entry) AS sources,
  page.sort_key AS page_key
FROM page
JOIN term name ON name.id = page.name
LEFT JOIN term chosen ON chosen.id = page.selected
LEFT JOIN candidates ON candidates.entry = page.entry
LEFT JOIN term started ON started.id = page.started
LEFT JOIN term written ON written.id = page.written
LEFT JOIN term label ON label.id = page.label
ORDER BY page.sort_key
