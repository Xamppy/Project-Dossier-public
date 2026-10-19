-- Consultas de la evidencia de almacenamiento (Fase 2).
-- psql -d dossier_evid_test -f docs/evidencias/fase2/_herramientas/consultas_almacenamiento.sql
-- Solo datos ficticios. Los hashes de contraseña se truncan a 12 caracteres.
\pset footer on
\echo '== Filas por tabla (pg_stat_user_tables, tras ANALYZE) =='
ANALYZE;
SELECT relname AS tabla, n_live_tup AS filas
FROM pg_stat_user_tables WHERE n_live_tup > 0 ORDER BY relname;

\echo '== organizations =='
SELECT left(id::text, 8) AS id, name, slug, plan, credits_balance, credits_monthly_limit,
       settings::text AS settings, created_at::timestamp(0) AS creada
FROM organizations ORDER BY created_at;

\echo '== users (password_hash truncado a 12 caracteres) =='
SELECT left(id::text, 8) AS id, email, full_name, locale,
       CASE WHEN password_hash IS NULL THEN '(sin contraseña)'
            ELSE left(password_hash, 12) || '…' END AS password_hash_12,
       length(password_hash) AS largo_hash, created_at::timestamp(0) AS creado
FROM users ORDER BY created_at;

\echo '== org_memberships =='
SELECT o.slug AS organizacion, u.email, m.role, m.is_primary_org
FROM org_memberships m JOIN organizations o ON o.id = m.organization_id
JOIN users u ON u.id = m.user_id ORDER BY o.slug;

\echo '== dossier_generation_jobs (estado y progreso) =='
SELECT left(j.id::text, 8) AS job, j.job_type, j.status, j.meeting_label,
       j.credits_estimated AS cred_est, j.credits_consumed AS cred_cons,
       jsonb_array_length(COALESCE(j.result_payload->'_progress'->'scopes', '[]'::jsonb)) AS scopes,
       jsonb_array_length(jsonb_path_query_array(j.result_payload, '$._progress.scopes[*].stages[*]')) AS etapas,
       jsonb_array_length(jsonb_path_query_array(j.result_payload, '$._progress.scopes[*].stages[*] ? (@.status == "completed")')) AS completadas,
       left(COALESCE(j.error_message, ''), 40) AS error,
       (j.completed_at - j.started_at)::interval(0) AS duracion
FROM dossier_generation_jobs j ORDER BY j.created_at;

\echo '== Estructura del progreso de un job (result_payload->_progress, primeras líneas) =='
SELECT left(jsonb_pretty(result_payload->'_progress'), 900) AS progreso
FROM dossier_generation_jobs WHERE job_type = 'person_manual' AND status = 'completed'
ORDER BY created_at LIMIT 1;

\echo '== dossiers (dossier_data JSONB) =='
SELECT left(d.id::text, 8) AS dossier, d.subject_name, d.status, d.depth_level,
       d.credits_consumed AS creditos, d.dossier_data->>'format' AS formato,
       jsonb_typeof(d.dossier_data) AS tipo, pg_column_size(d.dossier_data) AS bytes_jsonb,
       (SELECT count(*) FROM jsonb_object_keys(d.dossier_data)) AS claves
FROM dossiers d ORDER BY d.created_at;

\echo '== dossier_data de un dossier corporativo (claves de primer nivel) =='
SELECT d.subject_name, k AS clave, jsonb_typeof(d.dossier_data->k) AS tipo
FROM dossiers d, jsonb_object_keys(d.dossier_data) k
WHERE d.subject_name = 'Empresa de Prueba SA' ORDER BY k;

\echo '== credit_ledger (asientos creados por los triggers de cobro) =='
SELECT left(l.dossier_id::text, 8) AS dossier, d.subject_name, l.change_amount, l.balance_after,
       l.reason, l.created_at::timestamp(3) AS creado
FROM credit_ledger l LEFT JOIN dossiers d ON d.id = l.dossier_id ORDER BY l.created_at, l.balance_after DESC;

\echo '== Saldo de créditos: inicial (1000) − consumido = saldo actual =='
SELECT o.slug, o.credits_balance AS saldo_actual,
       (SELECT COALESCE(sum(credits_consumed), 0) FROM dossiers d WHERE d.organization_id = o.id) AS consumido_en_dossiers,
       (SELECT COALESCE(sum(change_amount), 0) FROM credit_ledger l WHERE l.organization_id = o.id) AS suma_ledger
FROM organizations o ORDER BY o.slug;
