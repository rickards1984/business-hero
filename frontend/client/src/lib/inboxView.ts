// ARIA-1a (Codex review 3): the Comms inbox's request ordering, as small pure
// helpers so they can be tested under Node.

/** Hands out a token per request; only the latest token is current. */
export function latestOnly() {
  let latest = 0;
  return {
    begin: () => ++latest,
    isCurrent: (token: number) => token === latest,
  };
}

/** Whether sorting has moved on since the status was last seen, so the list
 * should reload. `undefined` means no status has been seen yet (the page just
 * opened); `null` means seen, but nothing sorted yet. The first sort after
 * that (null → a time) reloads too (review 3, finding 1). */
export function sortingMovedOn(previous: string | null | undefined, next: string | null): boolean {
  return previous !== undefined && next !== previous;
}
