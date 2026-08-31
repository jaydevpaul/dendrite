import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ApiError } from "@/lib/api";
import { getMe, login, logout, signup, type Credentials, type User } from "./api";

export const meQueryKey = ["auth", "me"] as const;

/**
 * Our own callback shape rather than re-exporting TanStack's. Their mutation
 * callback arity has changed across v5 releases; call sites here only ever
 * want the resulting user, so depending on that detail buys nothing.
 */
interface AuthMutationOptions {
  onSuccess?: (user: User) => void;
}

/**
 * The single source of truth for "who is logged in".
 *
 * `retry: false` matters: the default would retry a legitimately-401 request
 * before settling, showing a loading state for no reason on every visit by a
 * logged-out user.
 */
export function useMe() {
  return useQuery({
    queryKey: meQueryKey,
    queryFn: getMe,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Signup and login both set the cookie server-side and return the user, so the
 * cache is written directly -- no refetch round-trip before the redirect.
 */
function useAuthMutation(
  mutationFn: (credentials: Credentials) => Promise<User>,
  options?: AuthMutationOptions,
) {
  const queryClient = useQueryClient();

  return useMutation<User, ApiError, Credentials>({
    mutationFn,
    onSuccess: (user) => {
      queryClient.setQueryData(meQueryKey, user);
      options?.onSuccess?.(user);
    },
  });
}

export function useSignup(options?: AuthMutationOptions) {
  // Signup auto-logs-in: the backend sets the cookie on 201, so there is no
  // second login step (auth_design.md section 4.1).
  return useAuthMutation(signup, options);
}

export function useLogin(options?: AuthMutationOptions) {
  return useAuthMutation(login, options);
}

export function useLogout(options?: { onSuccess?: () => void }) {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, void>({
    mutationFn: logout,
    onSuccess: () => {
      // Drop everything, not just the user: the whole cache is scoped to the
      // session that just ended. Without this, the next user to log in on this
      // browser would briefly see the previous one's data.
      queryClient.clear();
      queryClient.setQueryData(meQueryKey, null);
      options?.onSuccess?.();
    },
  });
}
