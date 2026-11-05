# TRADE-0 — production census (read-only; Mike's steps)

**Why:** TRADE-0 §5 narrows the database's own access rules before any site worker exists. Before writing that migration (041), we need to know what production actually has. Migration files aren't evidence of live state; a local replay can only be compared with production.

**All read-only.** Nothing changes. Run each query on **production (`oxblcmwhuwtobdhsfgyi`)** in the Supabase SQL editor and paste me the output. Every query returns **one row or a short list**, so the editor's 100-row export limit (the trap from September's census) can't cut anything off.

---

## C1 — Who is a member, and as what

```sql
SELECT count(*) AS members,
       count(*) FILTER (WHERE role = 'owner') AS owners,
       count(*) FILTER (WHERE role <> 'owner') AS non_owners,
       string_agg(DISTINCT role, ',') AS roles,
       count(*) FILTER (WHERE NOT is_active) AS inactive,
       count(*) FILTER (WHERE user_id IS NULL) AS pending_invites,
       (SELECT count(*) FROM (SELECT user_id FROM business_members WHERE is_active AND user_id IS NOT NULL
                              GROUP BY user_id HAVING count(*) > 1) x) AS people_in_several_businesses
FROM business_members;
```

**What I expect:** `non_owners` **0** and `roles` = `owner`. (The owner-only change assumes every current member is an owner.) `pending_invites` is probably 0. `people_in_several_businesses` tells me whether you're in both MSC and New Body under one login.

---

## C2 — Policies: does production still match the local copy?

```sql
SELECT count(*) AS policies,
       md5(string_agg(tablename||'|'||policyname||'|'||cmd||'|'||coalesce(qual,'')||'|'||coalesce(with_check,''),
                      E'\n' ORDER BY tablename, policyname)) AS fingerprint
FROM pg_policies WHERE schemaname = 'public';
```

**What I expect:** `95 | f81589fe733915543c26770182d9913e`, the same as the local copy (`scripts/rls-local.sh`). If it differs, production has drifted, and I'll send one more query to find where.

---

## C3 — The two views (open since September's census, BH-001 §5)

```sql
SELECT c.relname, pg_get_userbyid(c.relowner) AS owner,
       coalesce(array_to_string(c.reloptions, ','), '(none)') AS options,
       has_table_privilege('anon', c.oid, 'SELECT') AS anon_can_read,
       has_table_privilege('authenticated', c.oid, 'SELECT') AS signed_in_can_read,
       left(pg_get_viewdef(c.oid, true), 400) AS definition
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('v', 'm')
ORDER BY 1;
```

**What I expect:** two rows, `receptionist_call_stats` and `support_stats`. If `anon_can_read` is **true** and the first view groups by `business_id`, then anyone holding the app's public key can read every business's receptionist call figures without logging in. Nothing in the app uses either view, so 041 removes that access.

---

## C4 — File storage (not in the local copy)

```sql
SELECT (SELECT string_agg(id || CASE WHEN public THEN ' (public)' ELSE ' (private)' END, ', ' ORDER BY id)
          FROM storage.buckets) AS buckets,
       (SELECT count(*) FROM pg_policies WHERE schemaname = 'storage') AS storage_policies,
       (SELECT string_agg(policyname || ' [' || cmd || ']: ' ||
                          left(regexp_replace(coalesce(qual,'') || ' / ' || coalesce(with_check,''), '\s+', ' ', 'g'), 160),
                          E'\n' ORDER BY policyname)
          FROM pg_policies WHERE schemaname = 'storage') AS policies;
```

**What I expect:** a `logos` bucket (public). I'll check whether its upload, overwrite and delete rules test "member of the business" (which would include future site workers) or "owner".

---

## C5 — Functions a browser can call

```sql
SELECT string_agg(p.proname || CASE WHEN p.prosecdef THEN ' (definer)' ELSE '' END
                  || ' anon=' || has_function_privilege('anon', p.oid, 'EXECUTE')
                  || ' auth=' || has_function_privilege('authenticated', p.oid, 'EXECUTE'), E'\n' ORDER BY p.proname) AS functions
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public';
```

**What I expect:** the same 8 functions as the local copy:
- `is_business_member`, `is_platform_admin`, `setup_default_accounting_categories`, `update_updated_at_column` and `whoami (definer)`, each with anon=true and auth=true;
- `outreach_bind_message_version`, `outreach_freeze_approved_step` and `outreach_freeze_knowledge`, each with anon=false and auth=false.

---

## C6 — What a signed-in person may change in their own membership row

```sql
SELECT string_agg(DISTINCT privilege_type || '(' || column_name || ')', ', ') AS signed_in_privileges
FROM information_schema.column_privileges
WHERE table_schema = 'public' AND table_name = 'business_members' AND grantee = 'authenticated'
  AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE');
```

**What I expect:** UPDATE on `accepted_at` and `user_id` only, plus the table-level INSERT (which RLS blocks: there's no INSERT policy). Role can't be changed from a browser, which is good. 041 will still remove the direct "claim my invitation" path, because invitations will go through the backend (single use, expiry, cancellation).
