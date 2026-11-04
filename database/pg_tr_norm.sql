-- PostgreSQL: SQLite tr_norm() karşılığı (Türkçe arama)
CREATE OR REPLACE FUNCTION tr_norm(t text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT CASE
    WHEN t IS NULL THEN NULL
    ELSE lower(
      translate(
        replace(t, U&'\0307', ''),
        'İIıŞşĞğÜüÖöÇç',
        'iiissgguuooсс'
      )
    )
  END
$$;
