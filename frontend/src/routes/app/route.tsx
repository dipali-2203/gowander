import { createFileRoute, Outlet, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { currentUser, signOut, type AuthUser } from "@/lib/api";
import { AuthContext } from "@/lib/auth-context";
import { useTripStore } from "@/store/trip";

export const Route = createFileRoute("/app")({
  component: AppLayout,
});

function AppLayout() {
  const navigate = useNavigate();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checking, setChecking] = useState(true);
  const clearTripState = useTripStore((state) => state.clear);

  useEffect(() => {
    let active = true;
    clearTripState();
    currentUser()
      .then(({ user: authenticatedUser }) => {
        if (!active) return;
        setUser(authenticatedUser);
        if (!authenticatedUser.onboarding_completed && !authenticatedUser.onboarding_skipped) {
          void navigate({ to: "/app/onboarding", replace: true });
        }
      })
      .catch(() => {
        if (active) {
          clearTripState();
          void navigate({ to: "/login", replace: true });
        }
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, [navigate, clearTripState]);

  const logout = async () => {
    try {
      await signOut();
    } finally {
      setUser(null);
      clearTripState();
      await navigate({ to: "/login", replace: true });
    }
  };

  if (checking || !user)
    return (
      <div
        role="status"
        className="grid min-h-dvh place-items-center bg-background text-sm text-muted-foreground"
      >
        <span className="mr-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent" />
        Checking your session…
      </div>
    );
  return (
    <AuthContext.Provider value={{ user, setUser }}>
      <AppShell user={user} onLogout={logout}>
        <Outlet />
      </AppShell>
    </AuthContext.Provider>
  );
}
