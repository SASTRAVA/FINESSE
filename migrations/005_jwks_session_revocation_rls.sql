-- Tenant scoped key metadata and access-token revocation records.
ALTER TABLE jwks_signing_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE jwks_signing_keys FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy ON jwks_signing_keys;
CREATE POLICY tenant_isolation_policy ON jwks_signing_keys
    USING (tenant_id::text = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

ALTER TABLE revoked_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE revoked_sessions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy ON revoked_sessions;
CREATE POLICY tenant_isolation_policy ON revoked_sessions
    USING (tenant_id::text = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));
