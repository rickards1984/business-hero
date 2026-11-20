// The server's own reason when it gave one in plain words (OUT-28a fix,
// Mike 19 Nov 2026: "Email 2 still contains [Your Name]" was being hidden
// behind a generic message). Validation errors (a list) and anything that
// isn't a short sentence fall back to the general wording.
export function serverReason(text: string): string | null {
  const brace = text.indexOf('{');
  if (brace < 0) return null;
  try {
    const detail = JSON.parse(text.slice(brace)).detail;
    return typeof detail === 'string' && detail.trim() && detail.length <= 400 ? detail : null;
  } catch {
    return null;
  }
}
export function outreachError(error: unknown) {
  const text = error instanceof Error ? error.message : '';
  const status = Number(text.split(':')[0]);
  const reason = status >= 400 && status < 500 ? serverReason(text) : null;
  if (reason) return reason;
  if (text.startsWith('403:')) return 'Access denied. These controls require the active business owner and the relevant account access.';
  if (text.startsWith('404:')) return 'This record is unavailable in the current business.';
  if (text.startsWith('409:')) return 'The record changed or this action is blocked. Reload and review the current state before continuing.';
  if (text.startsWith('422:')) return 'Check the entered values. This request was not accepted.';
  if (status >= 500) return "Something went wrong on our side and nothing was saved. Please try again in a minute; if it keeps happening, tell support.";
  return 'Unavailable. Refresh to check the saved state before trying again.';
}
