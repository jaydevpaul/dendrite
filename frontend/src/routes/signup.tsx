import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { MIN_PASSWORD_LENGTH } from "@/features/auth/api";
import { useSignup } from "@/features/auth/queries";
import { Button } from "@/components/ui/button";
import { FormAlert } from "@/components/ui/form-alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthLayout, AuthLink } from "./auth-layout";

export default function SignupPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);

  // Signup auto-logs-in -- the backend sets the cookie on 201 -- so this lands
  // straight on the app rather than bouncing through the login form.
  const signup = useSignup({ onSuccess: () => navigate("/app", { replace: true }) });

  function onSubmit(event: FormEvent) {
    event.preventDefault();

    // Mirror the backend's own rule rather than inventing a stricter one, so
    // the two can never disagree about what is valid.
    if (password.length < MIN_PASSWORD_LENGTH) {
      setPasswordError(
        `Passwords must be at least ${MIN_PASSWORD_LENGTH} characters.`,
      );
      return;
    }

    setPasswordError(null);
    signup.mutate({ email: email.trim(), password });
  }

  const message =
    signup.error?.status === 409
      ? "That email already has an account. Log in instead, or use a different address."
      : signup.error?.message;

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Dendrite keeps your conversations and their branches private to you."
      footer={
        <>
          Already have an account? <AuthLink to="/login">Log in</AuthLink>
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
            autoComplete="new-password"
            required
            aria-invalid={passwordError ? true : undefined}
            aria-describedby="password-hint"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              if (passwordError) setPasswordError(null);
            }}
          />
          <p
            id="password-hint"
            className={
              passwordError
                ? "mt-[6px] text-[12.5px] text-danger"
                : "mt-[5px] text-[12px] text-muted"
            }
          >
            {passwordError ??
              `At least ${MIN_PASSWORD_LENGTH} characters. No other rules.`}
          </p>
        </div>

        <Button type="submit" size="block" disabled={signup.isPending}>
          {signup.isPending ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthLayout>
  );
}
