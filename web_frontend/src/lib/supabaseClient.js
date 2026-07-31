import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env?.VITE_SUPABASE_URL || "";
const supabaseAnonKey = import.meta.env?.VITE_SUPABASE_ANON_KEY || "";

/**
 * Client-side Supabase instance, used only for Auth (signUp,
 * signInWithPassword, resetPasswordForEmail, updateUser). Never used for
 * direct table access — that stays server-side with the service-role key.
 * `null` when env vars are unset, so callers can show a clear "not
 * configured" error instead of crashing.
 */
export const supabase =
  supabaseUrl && supabaseAnonKey ? createClient(supabaseUrl, supabaseAnonKey) : null;
