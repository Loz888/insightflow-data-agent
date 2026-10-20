-- Explicit opt-in for a newly created PILOT fixture/authorised data source only.
-- Never part of the legacy migration stream. All business tables become tenant scoped.
DO $$ DECLARE t record; BEGIN
 FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='business' LOOP
  EXECUTE format('ALTER TABLE business.%I ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT %L',t.tablename,'unassigned');
  EXECUTE format('ALTER TABLE business.%I ENABLE ROW LEVEL SECURITY',t.tablename);
  EXECUTE format('ALTER TABLE business.%I FORCE ROW LEVEL SECURITY',t.tablename);
  EXECUTE format('DROP POLICY IF EXISTS pilot_tenant ON business.%I',t.tablename);
  EXECUTE format('CREATE POLICY pilot_tenant ON business.%I FOR SELECT TO insightflow_reader USING (tenant_id = current_setting(%L,true))',t.tablename,'insightflow.tenant_id');
 END LOOP;
END $$;
