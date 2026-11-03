export function monitoringConfig(env: Record<string, string | undefined> = process.env) {
  if (env.MONITORING_ENABLED === undefined || env.MONITORING_ENABLED === "false") return null;
  if (env.MONITORING_ENABLED !== "true") throw new Error("Invalid MONITORING_ENABLED");
  let endpoint: URL;
  try {
    endpoint = new URL(env.MONITORING_ENDPOINT ?? "http://localhost:4318");
  } catch {
    throw new Error("Invalid MONITORING_ENDPOINT");
  }
  if (
    !["http:", "https:"].includes(endpoint.protocol) ||
    endpoint.username ||
    endpoint.password ||
    endpoint.pathname !== "/" ||
    endpoint.search ||
    endpoint.hash
  )
    throw new Error("Invalid MONITORING_ENDPOINT");
  function integer(key: string, fallback: number, min: number, max: number) {
    const raw = env[key] ?? String(fallback);
    const value = Number(raw);
    if (!/^\d+$/.test(raw) || !Number.isSafeInteger(value) || value < min || value > max) {
      throw new Error(`Invalid ${key}`);
    }
    return value;
  }
  return {
    endpoint: endpoint.origin,
    timeout: integer("MONITORING_EXPORT_TIMEOUT_MS", 1000, 100, 2000),
    queue: integer("MONITORING_QUEUE_SIZE", 256, 16, 1024),
    shutdown: integer("MONITORING_SHUTDOWN_MS", 3000, 100, 5000),
  };
}
