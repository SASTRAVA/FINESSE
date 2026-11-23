DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'knowledge_documents', 'knowledge_document_versions', 'connector_sync_states'
    ] LOOP
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
