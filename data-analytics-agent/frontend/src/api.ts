export class APIError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && typeof init.body === "string")
    headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const value = await response.json();
      message =
        typeof value.detail === "string"
          ? value.detail
          : JSON.stringify(value.detail ?? value);
    } catch {}
    throw new APIError(message, response.status);
  }
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
}
export function post<T>(path: string, body: unknown = {}) {
  return api<T>(path, { method: "POST", body: JSON.stringify(body) });
}
export function query(
  values: Record<string, string | number | boolean | undefined>,
) {
  return new URLSearchParams(
    Object.entries(values)
      .filter(([, value]) => value !== undefined)
      .map(([key, value]) => [key, String(value)]),
  ).toString();
}
export function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
