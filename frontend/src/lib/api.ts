/**
 * The one place that talks to the backend.
 *
 * Every request uses a RELATIVE path. In development Vite proxies /auth and
 * /health to http://localhost:8000, so the browser only ever sees one origin;
 * in production the container serves the built SPA next to the API. Either way
 * the session cookie is same-origin and CORS is never involved.
 */

/** Raised for any non-2xx response, carrying the backend's `detail` string. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * FastAPI reports failures as `{"detail": ...}`. For HTTPException the detail
 * is a string; for a 422 request-validation failure it is an array of error
 * objects. Flatten both into one human-readable sentence.
 */
async function readError(response: Response): Promise<string> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return response.statusText || "Something went wrong.";
  }

  const detail = (body as { detail?: unknown } | null)?.detail;

  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item as { msg?: unknown })?.msg)
      .filter((msg): msg is string => typeof msg === "string");
    if (messages.length > 0) return messages.join(". ");
  }

  return response.statusText || "Something went wrong.";
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
}

export async function request<T>(
  path: string,
  { method = "GET", body }: RequestOptions = {},
): Promise<T> {
  const response = await fetch(path, {
    method,
    // Same-origin thanks to the proxy, so this is belt-and-braces rather than
    // load-bearing -- but it makes the intent explicit: this app is entirely
    // cookie-authenticated and every call must carry the session.
    credentials: "include",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readError(response));
  }

  // 204 No Content (logout) has no body to parse.
  if (response.status === 204) return undefined as T;

  return (await response.json()) as T;
}
