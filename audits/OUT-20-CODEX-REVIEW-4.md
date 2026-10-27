**REQUEST CHANGES** — reviewed main at `2f9d822`, including `06e72e1..3c9c886`, against North Star **P8: Trust over cleverness**. No files modified, committed or pushed.

**P1 — none identified.** The remaining findings warrant a follow-up PR, but I found no must-fix-now production emergency.

**P2 findings**

1. **DMARC repair still drops valid settings and retains invalid reporting destinations.** At [outreach_setup.py:583](/Users/michaelrickards/dev/bh2-main-review/backend/services/outreach_setup.py:583), confirmed:
   - `fo=0 : 1` is discarded, although whitespace around the colon is valid.
   - `rua=mailto:reports@bad/#.com` is retained, preventing insertion of the fallback reporting address.

   The regexes do not fully implement the claimed [RFC 7489 grammar](https://www.rfc-editor.org/rfc/rfc7489.html#section-6.4). Normalise permitted whitespace and validate reporting URIs properly. Add regression tests for both examples.

2. **A DNS timeout is misdiagnosed as a malformed SPF record.** At [outreach_setup.py:530](/Users/michaelrickards/dev/bh2-main-review/backend/services/outreach_setup.py:530) and [the helper email:630](/Users/michaelrickards/dev/bh2-main-review/backend/services/outreach_setup.py:630), a timeout resolving `_spf.google.com` produces `manual` and tells the helper: “It has an entry that isn't written correctly.” I reproduced this with a syntactically valid existing record. Withholding a replacement is correct; claiming a syntax defect is not. Preserve an inconclusive evaluation result or use wording that does not invent the cause.

3. **The names.co.uk instructions give the wrong literal host-field entry.** The guide and helper email specify `@`, rendered directly by [OutreachSetupWizard.tsx:534](/Users/michaelrickards/dev/bh2-main-review/frontend/client/src/components/OutreachSetupWizard.tsx:534). Names.co.uk explicitly instructs users to **leave the hostname blank** when given `@`. Its linked article also primarily describes Namesco hosting settings rather than the editing procedure. Use provider-specific instructions and link directly to [Changing your domain’s DNS records](https://www.names.co.uk/support/articles/changing-your-domains-dns-settings/).

**Backlog**

- The [wizard banner:501](/Users/michaelrickards/dev/bh2-main-review/frontend/client/src/components/OutreachSetupWizard.tsx:501) always says settings need “adding,” including `edit`, `merge`, `manual` and `unknown`. Make this action-aware.
- Remove assurances that everyday email necessarily keeps working and authentication ensures inbox delivery. These exceed what the checks establish.
- Retire the contradictory legacy `advice` strings in `_evaluate`, which still recommend replacing SPF with a fresh provider-only record and adding DMARC indiscriminately. The wizard currently prefers `guide`, so this is not its active instruction path.

**Review-3 closure and regression evidence**

- **SPF finding closed.** The malformed-record test passes on HEAD and fails against `06e72e1`, executed entirely in memory. The wizard correctly hides the record value/copy controls for `manual`; its explanation directs owners to the helper email.
- **DMARC’s exact reported example is fixed**, and its regression test passes on HEAD and fails against `06e72e1`. Broader grammar correctness remains incomplete as described above.
- `test_every_offered_spf_value_passes_the_evaluator` passes on **both** versions. It provides useful coverage but does not independently detect the review-3 defect.
- Domain Connect remains absent from the visible wizard, including for names.co.uk. No unavailable connection action is advertised.

**Verification:** targeted pytest produced **27 passed, 11 fixture errors**; the errors require temporary database files prohibited by this read-only sandbox. Full `check.sh` was not run because it writes compilation artifacts. UI behaviour was inspected in code, not exercised in a browser.

After repair, Mike’s behaviour check is **Outreach setup → mailbox check → “I’ll do it myself” / “Send this to my web person”**: names.co.uk should say blank hostname, and an inconclusive DNS check should not claim malformed syntax.