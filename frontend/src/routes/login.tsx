import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useLogin } from "@/features/auth/queries";
import { Button } from "@/components/ui/button";
import { FormAlert } from "@/components/ui/form-alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthLayout, AuthLink } from "./auth-layout";

interface LocationState {
  from?: string;
}

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const from = (location.state as LocationState | null)?.from ?? "/app";
  const login = useLogin({
    onSuccess: () => navigate(from, { replace: true }),
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    login.mutate({ email: email.trim(), password });
  }

  // The backend returns one generic message for both "no such email" and
  // "wrong password", on purpose -- distinguishing them hands an attacker a
  // free oracle for which emails have accounts. Keep that property in the UI.
  const message =
    login.error?.status === 401
      ? "That email and password don't match an account."
      : login.error?.message;

  return (
    <AuthLayout
      title="Log in"
      subtitle="Pick up where your branches left off."
      footer={
        <>
          Need an account? <AuthLink to="/signup">Sign up</AuthLink>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate>
        {message ? <FormAlert className="mb-[18px]">{message}</FormAlert> : null}

        <div className="mb-[15px]">
          <Label htmlFor="email" className="mb-[5px]">
            Email
          </Label>
          <Input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>

        <div className="mb-[15px]">
          <Label htmlFor="password" className="mb-[5px]">
            Password
          </Label>
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>

        <Button type="submit" size="block" disabled={login.isPending}>
          {login.isPending ? "Logging in…" : "Log in"}
        </Button>
      </form>
    </AuthLayout>
  );
}
