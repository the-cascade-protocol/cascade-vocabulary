WITH
  k (type, import_kind, session_kind, connect_kind, sync_kind, server_kind, run_kind, started_at, was_generated_by,
     was_informed_by, revision_of, subject, label) AS (
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
      (SELECT id FROM term WHERE nt = '<https://ns.cascadeprotocol.org/cascade#revisionOf>'),
      (SELECT id FROM term WHERE nt = '<https://ns.cascadeprotocol.org/cascade#subject>'),
      (SELECT id FROM term WHERE nt = '<http://www.w3.org/2000/01/rdf-schema#label>'))
SELECT DISTINCT started.nt AS started, arrival.nt AS arrival, arrival_label.nt AS arrivalLabel
FROM k CROSS JOIN quad a ON a.p = k.type AND a.o IN (k.import_kind, k.session_kind, k.connect_kind, k.sync_kind)
CROSS JOIN quad s ON s.s = a.s AND s.p = k.started_at
CROSS JOIN term started ON started.id = s.o
CROSS JOIN term arrival ON arrival.id = a.s
LEFT JOIN quad al ON al.s = a.s AND al.p = k.label
LEFT JOIN term arrival_label ON arrival_label.id = al.o
WHERE ((a.o IN (k.import_kind, k.session_kind, k.connect_kind)
        AND EXISTS (SELECT 1 FROM quad r CROSS JOIN quad rf ON rf.s = r.s AND rf.p = k.revision_of
                    WHERE r.o = a.s AND r.p = k.was_generated_by
                      AND (EXISTS (SELECT 1 FROM quad su WHERE su.s = rf.o AND su.p = k.subject)
                           OR EXISTS (SELECT 1 FROM quad sv WHERE sv.s = rf.o AND sv.p = k.type AND sv.o = k.server_kind))))
       OR (a.o = k.sync_kind
           AND EXISTS (SELECT 1 FROM quad n CROSS JOIN quad r ON r.o = n.o AND r.p = k.was_generated_by
                       CROSS JOIN quad rf ON rf.s = r.s AND rf.p = k.revision_of
                       WHERE n.s = a.s AND n.p = k.was_informed_by
                         AND (EXISTS (SELECT 1 FROM quad su WHERE su.s = rf.o AND su.p = k.subject)
                              OR EXISTS (SELECT 1 FROM quad sv WHERE sv.s = rf.o AND sv.p = k.type AND sv.o = k.server_kind)))))
  AND NOT EXISTS (SELECT 1 FROM quad w CROSS JOIN quad t ON t.s = w.s AND t.p = k.type AND t.o = k.run_kind
                  WHERE w.o = a.s AND w.p = k.was_informed_by)
ORDER BY started.instant, arrival.kind, arrival.lex
