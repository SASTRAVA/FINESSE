-- SCIM credentials use a global, non-PII digest index only to resolve tenant
-- context; credential metadata and sessions remain in tenant-isolated tables.
DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['auth_sessions', 'scim_tokens', 'scim_token_index'] LOOP
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
