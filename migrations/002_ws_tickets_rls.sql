-- Tenant scope for short-lived WebSocket tickets issued by the API.
ALTER TABLE ws_tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE ws_tickets FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_policy ON ws_tickets;
CREATE POLICY tenant_isolation_policy ON ws_tickets
    USING (tenant_id::text = current_setting('app.current_tenant_id', true))
    WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true));
