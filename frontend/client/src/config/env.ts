/**
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

const normalizedApiBaseUrl = (apiBaseUrl as string).replace(/\/+$/, '');

export const config = {
  apiBaseUrl: normalizedApiBaseUrl,
} as const;


