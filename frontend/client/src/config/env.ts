Frontend: wire Vite env vars + API base URL routing/**
 * Environment configuration module.
 * Centralizes all environment variable access with runtime validation.
 */

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL;

if (!apiBaseUrl) {
  throw new Error(
    'Missing required environment variable: VITE_API_BASE_URL. ' +
    'Please set this in your .env file or deployment environment.'
  );
}

export const config = {
  apiBaseUrl: apiBaseUrl as string,
} as const;


