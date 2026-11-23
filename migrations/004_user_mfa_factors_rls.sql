-- TOTP enrollment and replay/recovery state. Payload fields are encrypted or
-- hashed by the application before persistence.
ALTER TABLE user_mfa_factors ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_mfa_factors FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy ON user_mfa_factors;
CREATE POLICY tenant_isolation_policy ON user_mfa_factors
    USING (tenant_id::text = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

-- Short-lived, single-use password-authentication challenges for MFA step-up.
ALTER TABLE auth_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_challenges FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy ON auth_challenges;
CREATE POLICY tenant_isolation_policy ON auth_challenges
    USING (tenant_id::text = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));

-- Tenant-controlled MFA policy; a tenant can require MFA for every role.
ALTER TABLE tenant_identity_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_identity_settings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy ON tenant_identity_settings;
CREATE POLICY tenant_isolation_policy ON tenant_identity_settings
    USING (tenant_id::text = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));
