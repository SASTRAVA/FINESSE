const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const WS_BASE_URL = (import.meta.env.VITE_WS_BASE_URL ?? "").replace(/\/$/, "");

export function apiUrl(path: string): string {
  if (!path.startsWith("/")) throw new Error("API paths must be absolute paths");
  return `${API_BASE_URL}${path}`;
}

export function ticketedWebSocketUrl(ticket: string): string {
  if (!ticket) throw new Error("A short-lived WebSocket ticket is required");
  const configured = WS_BASE_URL || API_BASE_URL || window.location.origin;
  const url = new URL(configured, window.location.origin);
  url.protocol = url.protocol === "https:" || url.protocol === "wss:" ? "wss:" : "ws:";
  url.pathname = `${url.pathname.replace(/\/$/, "")}/ws`;
  url.search = new URLSearchParams({ ticket }).toString();
  return url.toString();
}
