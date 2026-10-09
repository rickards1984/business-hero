## TICKET BH-012 — receptionist metering, caps and visible usage (RC1 P0-2)

**Outcome**  Receptionist minutes are counted, capped and shown: a plan's
allowance cannot be silently exceeded, a call is never longer than 20
minutes, overage is opt-in with an owner-set cap, and the owner sees usage
before the limit.

**Current evidence**  `usage_meters` and `businesses.metered_usage_enabled /
monthly_spend_cap_gbp` exist in production (033) and no code references
them (`docs/CURRENT_STATE.md` §5, "Metering — absent"). The receptionist
answers every call with no limit (`receptionist_call_handler.py`);
`receptionist_configs.max_call_duration_seconds` is not enforced.
`audits/PRICING-MODEL.md`: "one customer … runs £400 of calls through a
£129 plan before anyone notices".

**Serves**  RC1 P0-2 (money). Unblocks the Aria voice repair (ADR 0001 D2).

**Rules**  ENTITLEMENT-SPEC PART E and DECISION 2; Mike's decisions of
10 Oct 2026 (ADR 0001 D19).

**Schema**  None needed. `usage_meters` has `UNIQUE (business_id, meter,
period)`, a `YYYY-MM` check, RLS with member SELECT, client SELECT only
(staging, read 10 Oct 2026). Production expected identical (033); a
read-only check is on Mike's list. `businesses` columns are backend-only
since 030b Release 2.

**Stage 1 (this commit)**  `backend/tests/test_metering.py` — 34 strict-xfail
tests. No implementation.

**Stage 2, after Mike approves the tests**
1. `backend/services/metering.py` per the contract in the test docstring;
   increments as an atomic upsert on the unique index.
2. `backend/usage_api.py`: `GET /v1/usage`, `PUT /v1/usage/metering`
   (registered in `main.py`, one line).
3. Receptionist: `admit_call` before answering (neutral message if
   blocked, owner notified); the media stream ends a call at
   `call_time_limit_seconds`; `record_call` at call end from actual duration.
4. Notifications: email + in-app banner state (+ WhatsApp when on), once per
   month per state.
5. Frontend: usage shown in the Receptionist tab, with the metering switch
   and cap; a banner when the allowance is used up.

**Non-goals**  Billing overage through Stripe (the meter records it;
invoicing it is a follow-up). Aria voice metering (ships with the voice
repair). Outreach meters.

**Security & data risk**  RED (money). Tenant: meters keyed by the
authenticated business only. Fail-safe question for review: if the meter
cannot be read when a call arrives, answer or refuse? (BH-006 chose to
answer: "the cost of a wrong refusal is a missed customer".)

**Builder** Claude Code  **Reviewer** Codex  **Branch** `ticket/BH-012-metering`
**Budget band** L  **Max repair cycles** 3
**Status** in progress — Stage 1 awaiting Mike's review of the tests
