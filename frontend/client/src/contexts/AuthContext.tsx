import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { supabase } from '@/lib/supabase';
import type { User, Session } from '@supabase/supabase-js';

interface AuthContextType {
  user: User | null;
  session: Session | null;
  isAdmin: boolean;
  loading: boolean;
  adminLoading: boolean;
  signIn: (email: string, password: string) => Promise<{ error: Error | null }>;
  signOut: () => Promise<void>;
  checkAdminStatus: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [adminLoading, setAdminLoading] = useState(true);

  const checkAdminStatus = async (): Promise<boolean> => {
    setAdminLoading(true);
    
    try {
      // Get current session to ensure we have the latest user
      const { data: { session: currentSession } } = await supabase.auth.getSession();
      const currentUser = currentSession?.user;
      
      if (!currentUser) {
        setIsAdmin(false);
        return false;
      }
      
      // Use maybeSingle() instead of single() to avoid 406 errors when no rows exist
      const { data, error } = await supabase
        .from('platform_admins')
        .select('user_id')
        .eq('user_id', currentUser.id)
        .maybeSingle();
      
      // maybeSingle() returns null for data when no rows found (no error)
      // Only treat it as an error if there's an actual error (not a 406)
      const adminStatus = !error && !!data;
      setIsAdmin(adminStatus);
      return adminStatus;
    } catch (err) {
      // Handle any unexpected errors gracefully
      setIsAdmin(false);
      return false;
    } finally {
      setAdminLoading(false);
    }
  };

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setUser(session?.user ?? null);
      setLoading(false);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (_event, session) => {
        setSession(session);
        setUser(prev => {
          const next = session?.user ?? null;
          if (prev?.id === next?.id) return prev;
          return next;
        });
        setLoading(false);
      }
    );

    return () => subscription.unsubscribe();
  }, []);

  // Link any pending membership invitations to this user
  const linkMembership = async (currentUser: User) => {
    try {
      await supabase
        .from('business_members')
        .update({ 
          user_id: currentUser.id, 
          accepted_at: new Date().toISOString() 
        })
        .eq('invited_email', currentUser.email)
        .is('user_id', null);
    } catch (err) {
      console.error('Failed to link membership:', err);
    }
  };

  useEffect(() => {
    if (user) {
      // Link any pending invitations, then check admin status
      linkMembership(user).then(() => checkAdminStatus());
    } else {
      setIsAdmin(false);
      setAdminLoading(false);
    }
  }, [user]);

  const signIn = async (email: string, password: string) => {
    try {
      const { error } = await supabase.auth.signInWithPassword({
        email,
        password,
      });
      return { error: error as Error | null };
    } catch (err: any) {
      console.error('SignIn network error:', err);
      return { error: new Error(err?.message || 'Network error: Failed to connect to Supabase') };
    }
  };

  const signOut = async () => {
    await supabase.auth.signOut();
    setIsAdmin(false);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        session,
        isAdmin,
        loading,
        adminLoading,
        signIn,
        signOut,
        checkAdminStatus,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
