-- 038 — OUT-7 Stage A DRAFT FOR REVIEW. Never applied remotely by this task.
-- North Star P2/P4/P5/P9. No ORM registration, data population or activation.
-- Follow audits/038-PROD-RUNBOOK.md; Section 1 runs separately, autocommit.

-- SECTION 1 — EXISTING PARENT INDEX: OUTSIDE ANY TRANSACTION.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS outreach_replies_out7_identity_key
  ON public.outreach_replies (business_id, prospect_id, mailbox_id, id);

-- SECTION 2 — ATTACH KEY, CREATE TABLES, CHECKS, RLS AND GRANTS.
BEGIN;
SET LOCAL lock_timeout = '5s';
DO $attach$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
    WHERE conrelid='public.outreach_replies'::regclass AND conname='outreach_replies_out7_identity_key') THEN
    ALTER TABLE public.outreach_replies ADD CONSTRAINT outreach_replies_out7_identity_key
      UNIQUE USING INDEX outreach_replies_out7_identity_key;
  END IF;
END;
$attach$;

CREATE TABLE IF NOT EXISTS public.outreach_knowledge (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  brand_id uuid NOT NULL,
  topic text NOT NULL CHECK (length(btrim(topic)) BETWEEN 1 AND 200),
  answer text NOT NULL CHECK (length(btrim(answer)) BETWEEN 1 AND 4000),
  source_reference text NOT NULL CHECK (length(btrim(source_reference)) BETWEEN 1 AND 2000),
  version integer NOT NULL CHECK (version > 0),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','retired')),
  approved_by uuid,
  approved_at timestamptz,
  review_due_at timestamptz NOT NULL,
  retired_at timestamptz,
  UNIQUE (business_id, id),
  UNIQUE (business_id, brand_id, topic, version),
  FOREIGN KEY (business_id, brand_id) REFERENCES public.outreach_brands (business_id, id),
  CHECK ((approved_by IS NULL) = (approved_at IS NULL)),
  CHECK (status <> 'approved' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)),
  CHECK (approved_at IS NULL OR review_due_at > approved_at),
  CHECK ((status = 'retired') = (retired_at IS NOT NULL)),
  CHECK (retired_at IS NULL OR approved_at IS NULL OR retired_at >= approved_at)
);
REVOKE ALL ON public.outreach_knowledge FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_knowledge ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.outreach_reply_slots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  prospect_id uuid NOT NULL,
  reply_id uuid NOT NULL,
  mailbox_id uuid NOT NULL,
  action_id uuid NOT NULL,
  message_id uuid,
  state text NOT NULL DEFAULT 'reserved' CHECK (state IN ('reserved','accepted','unknown','released')),
  generation integer NOT NULL DEFAULT 1 CHECK (generation > 0),
  reserved_at timestamptz NOT NULL,
  dispatched_at timestamptz,
  settled_at timestamptz,
  released_at timestamptz,
  release_reason text CHECK (length(btrim(release_reason)) BETWEEN 1 AND 1000),
  outcome_evidence jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(outcome_evidence) = 'object' AND octet_length(outcome_evidence::text) <= 16384),
  payload_hash text CHECK (length(payload_hash) = 64),
  UNIQUE (business_id, id),
  UNIQUE (business_id, prospect_id),
  UNIQUE (business_id, reply_id),
  UNIQUE (business_id, action_id),
  FOREIGN KEY (business_id, prospect_id) REFERENCES public.outreach_prospects (business_id, id),
  FOREIGN KEY (business_id, prospect_id, mailbox_id, reply_id)
    REFERENCES public.outreach_replies (business_id, prospect_id, mailbox_id, id),
  FOREIGN KEY (business_id, mailbox_id) REFERENCES public.email_accounts (business_id, id),
  FOREIGN KEY (business_id, action_id) REFERENCES public.aria_actions (business_id, id),
  FOREIGN KEY (business_id, prospect_id, mailbox_id, message_id)
    REFERENCES public.outreach_messages (business_id, prospect_id, mailbox_id, id),
  FOREIGN KEY (business_id, action_id, message_id)
    REFERENCES public.outreach_messages (business_id, action_id, id),
  CHECK (dispatched_at IS NULL OR (message_id IS NOT NULL AND payload_hash IS NOT NULL AND dispatched_at >= reserved_at)),
  CHECK (state NOT IN ('accepted','unknown') OR dispatched_at IS NOT NULL),
  CHECK (state <> 'accepted' OR settled_at IS NOT NULL),
  CHECK (settled_at IS NULL OR settled_at >= reserved_at),
  CHECK ((state = 'released') = (released_at IS NOT NULL)),
  CHECK ((state = 'released') = (release_reason IS NOT NULL)),
  CHECK (released_at IS NULL OR (released_at >= reserved_at AND settled_at IS NOT NULL AND outcome_evidence <> '{}'::jsonb))
);
REVOKE ALL ON public.outreach_reply_slots FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.outreach_reply_slots ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS outreach_knowledge_review_idx
  ON public.outreach_knowledge (business_id, brand_id, status, review_due_at);
CREATE UNIQUE INDEX IF NOT EXISTS outreach_knowledge_one_approved_idx
  ON public.outreach_knowledge (business_id, brand_id, topic) WHERE status='approved';
CREATE INDEX IF NOT EXISTS outreach_reply_slots_state_idx
  ON public.outreach_reply_slots (business_id, state, updated_at);

-- Approved factual content and its review window cannot be rewritten.
-- Retire old version and insert/approve a new version in one transaction.
CREATE OR REPLACE FUNCTION public.outreach_freeze_knowledge()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $fn$
BEGIN
  IF OLD.status IN ('approved','retired') THEN
    IF (to_jsonb(NEW) - ARRAY['updated_at','status','retired_at']) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['updated_at','status','retired_at'])
       OR (OLD.status='retired' AND (NEW.status <> 'retired' OR NEW.retired_at IS DISTINCT FROM OLD.retired_at))
       OR (OLD.status='approved' AND NEW.status NOT IN ('approved','retired')) THEN
      RAISE EXCEPTION 'Approved/retired knowledge version is immutable' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$fn$;
REVOKE ALL ON FUNCTION public.outreach_freeze_knowledge() FROM PUBLIC, anon, authenticated;
DROP TRIGGER IF EXISTS outreach_knowledge_immutable ON public.outreach_knowledge;
CREATE TRIGGER outreach_knowledge_immutable BEFORE UPDATE ON public.outreach_knowledge
  FOR EACH ROW EXECUTE FUNCTION public.outreach_freeze_knowledge();

-- Re-paste clears column grants too. Never alter shared roles to hide inheritance.
DO $columns$
DECLARE t text; c text;
BEGIN
  FOREACH t IN ARRAY ARRAY['outreach_knowledge','outreach_reply_slots'] LOOP
    SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum) INTO c
      FROM pg_attribute WHERE attrelid=('public.' || t)::regclass AND attnum > 0 AND NOT attisdropped;
    EXECUTE format('REVOKE SELECT (%s), INSERT (%s), UPDATE (%s), REFERENCES (%s) ON public.%I FROM PUBLIC, anon, authenticated, service_role',c,c,c,c,t);
  END LOOP;
END;
$columns$;

DROP POLICY IF EXISTS outreach_knowledge_member_read ON public.outreach_knowledge;
CREATE POLICY outreach_knowledge_member_read ON public.outreach_knowledge
  AS PERMISSIVE FOR SELECT TO authenticated
  USING (public.is_business_member(auth.uid(), business_id));
GRANT SELECT ON public.outreach_knowledge TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON public.outreach_knowledge, public.outreach_reply_slots TO service_role;

DO $grants$
DECLARE t text; r text; p text; allowed boolean; actual boolean;
BEGIN
  FOREACH t IN ARRAY ARRAY['outreach_knowledge','outreach_reply_slots'] LOOP
    IF has_table_privilege('service_role','public.' || t,'TRUNCATE') THEN
      RAISE EXCEPTION 'Unexpected effective service TRUNCATE grant on %',t;
    END IF;
    FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
      FOREACH p IN ARRAY ARRAY['SELECT','INSERT','UPDATE','REFERENCES','DELETE','TRUNCATE','TRIGGER'] LOOP
        allowed := r='authenticated' AND p='SELECT' AND t='outreach_knowledge';
        IF p IN ('SELECT','INSERT','UPDATE','REFERENCES') THEN
          actual := has_any_column_privilege(r,'public.' || t,p);
        ELSE
          actual := has_table_privilege(r,'public.' || t,p);
        END IF;
        IF actual IS DISTINCT FROM allowed THEN
          RAISE EXCEPTION 'Unexpected effective grant: % % %',r,t,p;
        END IF;
      END LOOP;
    END LOOP;
  END LOOP;
END;
$grants$;
COMMIT;
