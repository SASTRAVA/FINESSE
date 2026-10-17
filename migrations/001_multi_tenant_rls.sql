-- PostgreSQL 16 companion policies for deployments using relational storage.
-- Apply after creating the tenant-aware tables. Set app.current_tenant_id per transaction.
DO $$
DECLARE
    table_name text;
    tenant_tables text[] := ARRAY[
        'tenants', 'users', 'services', 'icps', 'campaigns', 'companies', 'contacts',
        'leads', 'lead_campaigns', 'email_messages', 'email_events', 'calls',
        'consent_records', 'suppression_entries', 'activities', 'meetings', 'jobs',
        'audit_logs', 'gatekeeper_approvals', 'scan_tasks', 'scan_findings',
        'scan_evidence', 'catalog_repositories', 'tenant_secrets'
    ];
BEGIN
    FOREACH table_name IN ARRAY tenant_tables LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_policy ON %I', table_name);
        EXECUTE format(
            'CREATE POLICY tenant_isolation_policy ON %I USING '
            || '(tenant_id::text = current_setting(''app.current_tenant_id'', true)) '
            || 'WITH CHECK (tenant_id::text = current_setting(''app.current_tenant_id'', true))',
            table_name
        );
    END LOOP;
END $$;
