/**
 * frontend/src/store/auth.ts — Auth state management (localStorage-based, no external deps)
 */

const TOKEN_KEY = "findme_auth_token";
const DISMISSED_KEY = "findme_reg_dismissed";

export interface User {
  id: string;
  email: string;
  display_name: string | null;
}

export interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
}

export function saveAuth(token: string, user: User): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function getSavedToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getAuthHeader(): Record<string, string> {
  const token = getSavedToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function isRegistrationDismissed(): boolean {
  return localStorage.getItem(DISMISSED_KEY) === "true";
}

export function dismissRegistration(): void {
  localStorage.setItem(DISMISSED_KEY, "true");
}
