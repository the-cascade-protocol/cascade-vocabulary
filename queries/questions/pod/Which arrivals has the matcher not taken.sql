WITH
  k (type, import_kind, session_kind, connect_kind, sync_kind, server_kind, run_kind, started_at, was_generated_by,
     was_informed_by, was_revision_of, took_records_naming, revision_of, current_version, patient, subject, label) AS (
    SELECT (SELECT id FROM term WHERE nt = '<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>'),
      (SELECT id FROM term WHERE nt = '<https://ns.cascadeprotocol.org/cascade#DocumentImport>'),
      (SELECT id FROM term WHERE nt = '<https://ns.cascadeprotocol.org/cascade#HandEntrySession>'),
      (SELECT id FROM term WHERE nt = '<https://ns.cascadeprotocol.org/cascade#ConnectToServer>'),
      (SELECT id FROM term WHERE nt = '<https://ns.cascadeprotocol.org/cascade#SyncFromAnotherWriter>'),
      (SELECT id FROM term WHERE nt = '<https://ns.cascadeprotocol.org/cascade#Server>'),
      (SELECT id FROM term WHERE nt = '<https://ns.cascadeprotocol.org/cascade#MatcherRun>'),
      (SELECT id FROM term WHERE nt = '<http://www.w3.org/ns/prov#startedAtTime>'),
      (SELECT id FROM term WHERE nt = '<http://www.w3.org/ns/prov#wasGeneratedBy>'),
      (SELECT id FROM term WHERE nt = '<http://www.w3.org/ns/prov#wasInformedBy>'),
      (SELECT id FROM term WHERE nt = '<http://www.w3.org/ns/prov#wasRevisionOf>'),
      (SELECT id FROM term WHERE nt = '<https://ns.cascadeprotocol.org/cascade#tookRecordsWhoseCurrentVersionNamesPatient>'),
      (SELECT id FROM term WHERE nt = '<https://ns.cascadeprotocol.org/cascade#revisionOf>'),
      (SELECT id FROM term WHERE nt = '<http://purl.org/pav/hasCurrentVersion>'),
      (SELECT id FROM term WHERE nt = '<https://ns.cascadeprotocol.org/cascade#patient>'),
      (SELECT id FROM term WHERE nt = '<https://ns.cascadeprotocol.org/cascade#subject>'),
      (SELECT id FROM term WHERE nt = '<http://www.w3.org/2000/01/rdf-schema#label>')),
  arrivals (arrival) AS (
    SELECT DISTINCT a.s FROM k CROSS JOIN quad a ON a.p = k.type AND a.o IN (k.import_kind, k.session_kind, k.connect_kind, k.sync_kind)),
  sources (arrival, source) AS (
    SELECT arrival, arrival FROM arrivals
    UNION
    SELECT arrivals.arrival, n.o FROM arrivals CROSS JOIN k CROSS JOIN quad n ON n.s = arrivals.arrival AND n.p = k.was_informed_by),
  named (arrival, patient) AS (
    SELECT w.o, u.o FROM k
    CROSS JOIN quad u ON u.p = k.took_records_naming
    CROSS JOIN quad t ON t.s = u.s AND t.p = k.type AND t.o = k.run_kind
    CROSS JOIN quad w ON w.s = u.s AND w.p = k.was_informed_by
    UNION
    SELECT n.o, u.o FROM k
    CROSS JOIN quad u ON u.p = k.took_records_naming
    CROSS JOIN quad t ON t.s = u.s AND t.p = k.type AND t.o = k.run_kind
    CROSS JOIN quad w ON w.s = u.s AND w.p = k.was_informed_by
    CROSS JOIN quad y ON y.s = w.o AND y.p = k.type AND y.o = k.sync_kind
    CROSS JOIN quad n ON n.s = w.o AND n.p = k.was_informed_by),
  owed (arrival, patient) AS (
    SELECT a.s, cp.o FROM k
    CROSS JOIN quad a ON a.p = k.type AND a.o IN (k.import_kind, k.session_kind, k.connect_kind)
    CROSS JOIN quad r ON r.o = a.s AND r.p = k.was_generated_by
    CROSS JOIN quad rf ON rf.s = r.s AND rf.p = k.revision_of
    LEFT JOIN quad e ON e.s = r.s AND e.p = k.was_revision_of
    CROSS JOIN quad su ON su.s = rf.o AND su.p = k.subject
    CROSS JOIN quad cv ON cv.s = rf.o AND cv.p = k.current_version
    CROSS JOIN quad cp ON cp.s = cv.o AND cp.p = k.patient
    WHERE e.s IS NULL
    EXCEPT
    SELECT arrival, patient FROM named)
SELECT DISTINCT started.nt AS started, arrival.nt AS arrival, arrival_label.nt AS arrivalLabel
FROM arrivals CROSS JOIN k
CROSS JOIN quad s ON s.s = arrivals.arrival AND s.p = k.started_at
CROSS JOIN term started ON started.id = s.o
CROSS JOIN term arrival ON arrival.id = arrivals.arrival
LEFT JOIN quad al ON al.s = arrivals.arrival AND al.p = k.label
LEFT JOIN term arrival_label ON arrival_label.id = al.o
WHERE (NOT EXISTS (SELECT 1 FROM quad w CROSS JOIN quad t ON t.s = w.s AND t.p = k.type AND t.o = k.run_kind
                   WHERE w.o = arrivals.arrival AND w.p = k.was_informed_by)
       AND EXISTS (SELECT 1 FROM sources CROSS JOIN quad r ON r.o = sources.source AND r.p = k.was_generated_by
                   CROSS JOIN quad rf ON rf.s = r.s AND rf.p = k.revision_of
                   WHERE sources.arrival = arrivals.arrival
                     AND (EXISTS (SELECT 1 FROM quad su WHERE su.s = rf.o AND su.p = k.subject)
                          OR EXISTS (SELECT 1 FROM quad sv WHERE sv.s = rf.o AND sv.p = k.type AND sv.o = k.server_kind))))
   OR arrivals.arrival IN (SELECT arrival FROM owed)
ORDER BY started.instant, arrival.kind, arrival.lex
