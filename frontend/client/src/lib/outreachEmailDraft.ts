// OUT-28a: the owner's unsaved changes to a campaign's three emails.
//
// A draft is a SNAPSHOT: the three emails and the campaign version as they
// were when editing began, plus the owner's changes. Saving always sends all
// three from the snapshot with the snapshot's version, so a save made
// elsewhere meanwhile is refused by the server (409) instead of overwritten
// (Codex OUT-28 review 1, finding 3). Changes to several emails build up
// before one save, so three "[Your Name]"s can be fixed in one go (finding 2).
// Tested by backend/tests/test_outreach_email_draft.py.

export interface DraftEmail { ordinal: number; subject: string; body: string }
export interface Draft { version: number; original: DraftEmail[]; emails: DraftEmail[] }
export interface Problem { ordinal: number; kind: 'placeholder' | 'curly' | 'blank'; text: string }

// A first warning while typing. The server's check is the one that counts.
export const PLACEHOLDER = /\[[^\]\n]{1,40}\]|\{\{?[^}\n]{0,40}\}\}?|<[A-Z][A-Z _]{1,30}>/;
const CURLY = /[{}]/;

export function startDraft(campaign: { version: number; emails: DraftEmail[] }): Draft {
  const emails = [...campaign.emails].sort((a, b) => a.ordinal - b.ordinal)
    .map(e => ({ ordinal: e.ordinal, subject: e.subject, body: e.body }));
  return { version: campaign.version, original: emails.map(e => ({ ...e })), emails };
}

export function edit(draft: Draft, ordinal: number, change: { subject?: string; body?: string }): Draft {
  return { ...draft, emails: draft.emails.map(e => (e.ordinal === ordinal
    ? { ...e, ...(change.subject !== undefined ? { subject: change.subject.replace(/[\r\n]+/g, ' ') } : {}),
        ...(change.body !== undefined ? { body: change.body } : {}) }
    : e)) };
}

export function changed(draft: Draft, ordinal?: number): boolean {
  return draft.emails.some((e, i) => (ordinal === undefined || e.ordinal === ordinal)
    && (e.subject !== draft.original[i].subject || e.body !== draft.original[i].body));
}

export function problems(draft: Draft): Problem[] {
  const out: Problem[] = [];
  for (const e of draft.emails) {
    const found = (e.subject + '\n' + e.body).match(PLACEHOLDER)?.[0];
    if (!e.subject.trim() || !e.body.trim()) out.push({ ordinal: e.ordinal, kind: 'blank', text: 'needs a subject and a message' });
    else if (found) out.push({ ordinal: e.ordinal, kind: 'placeholder', text: found });
    else if (CURLY.test(e.subject + e.body)) out.push({ ordinal: e.ordinal, kind: 'curly', text: '{ }' });
  }
  return out;
}

export function stale(draft: Draft, latestVersion: number | undefined): boolean {
  return latestVersion !== undefined && latestVersion !== draft.version;
}

export function payload(draft: Draft): { version: number; emails: DraftEmail[] } {
  return { version: draft.version, emails: draft.emails.map(e => ({ ...e })) };
}
