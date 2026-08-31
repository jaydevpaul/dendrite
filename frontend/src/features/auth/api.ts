import { ApiError, request } from "@/lib/api";

/** Mirrors the backend's `UserOut` schema -- everything we say about a user. */
export interface User {
  id: string;
  email: string;
}

export interface Credentials {
  email: string;
  password: string;
}

/** Matches the backend's `Field(min_length=8)`. No composition rules, by design. */
export const MIN_PASSWORD_LENGTH = 8;

export function signup(body: Credentials) {
  return request<User>("/auth/signup", { method: "POST", body });
}

export function login(body: Credentials) {
  return request<User>("/auth/login", { method: "POST", body });
}

export function logout() {
  return request<void>("/auth/logout", { method: "POST" });
}

/**
 * Resolve the session cookie into a user.
 *
 * A 401 here is not an error -- it is the ordinary "nobody is logged in"
 * answer, and it is what the protected-route wrapper reads. Anything else
 * (the API being down, a 500) still throws, because that genuinely is broken
 * and must not be silently rendered as a logged-out state.
 */
export async function getMe(): Promise<User | null> {
  try {
    return await request<User>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}
