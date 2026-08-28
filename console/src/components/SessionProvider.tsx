import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { cloud, type AppRole, type CloudUser } from "@/lib/cloud";

interface SessionValue {
  user: CloudUser | null;
  loading: boolean;
  roles: AppRole[];
  can: (role: AppRole) => boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, displayName: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CloudUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    cloud.getCurrentUser().then((current) => {
      if (!active) return;
      setUser(current);
      setLoading(false);
    });
    const unsubscribe = cloud.onAuthChange((next) => active && setUser(next));
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  const value = useMemo<SessionValue>(
    () => ({
      user,
      loading,
      roles: user?.roles ?? [],
      // Administrators pass every check. Every other role is checked exactly.
      can: (role) => !!user && (user.roles.includes("administrator") || user.roles.includes(role)),
      signIn: async (email, password) => setUser(await cloud.signIn(email, password)),
      signUp: async (email, password, displayName) => setUser(await cloud.signUp(email, password, displayName)),
      signOut: async () => {
        await cloud.signOut();
        setUser(null);
      },
      refresh: async () => setUser(await cloud.getCurrentUser()),
    }),
    [user, loading],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside a SessionProvider");
  return value;
}
