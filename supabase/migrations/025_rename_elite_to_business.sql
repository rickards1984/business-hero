-- 025: Rename elite tier to business, add setup_fee_gbp, update plan_definitions

-- Add setup_fee_gbp column to plan_definitions
ALTER TABLE plan_definitions
  ADD COLUMN IF NOT EXISTS setup_fee_gbp NUMERIC(10,2);

-- Update any businesses still on 'elite' to 'business'
UPDATE businesses SET plan_tier = 'business' WHERE plan_tier = 'elite';

-- Update the plan_tier CHECK constraint to accept 'business' instead of 'elite'
ALTER TABLE businesses DROP CONSTRAINT IF EXISTS businesses_plan_tier_check;
ALTER TABLE businesses
  ADD CONSTRAINT businesses_plan_tier_check
    CHECK (plan_tier IN ('starter','pro','business','beta','paused'));

-- Remove old enterprise/elite rows and upsert the three website-aligned tiers
DELETE FROM plan_definitions WHERE id IN ('enterprise', 'elite');

INSERT INTO plan_definitions (id, name, description, monthly_price_gbp, setup_fee_gbp, features, limits, sort_order) VALUES
  ('starter', 'Starter', 'Essential tools to get your business online — £49/mo + £149 setup',
   49.00, 149.00,
   '{"email":true,"accounting":true,"ai_briefings":true,"whatsapp_briefing":true,"receptionist":false,"quoting":false,"calendar_booking":false}',
   '{"users":1,"businesses":1}',
   1),
  ('pro', 'Pro', 'Everything in Starter plus receptionist, quoting & calendar — £99/mo + £249 setup',
   99.00, 249.00,
   '{"email":true,"accounting":true,"ai_briefings":true,"whatsapp_briefing":true,"receptionist":true,"quoting":true,"calendar_booking":true}',
   '{"users":5,"businesses":3}',
   2),
  ('business', 'Business', 'Full platform access with premium support — £199/mo + £499 setup',
   199.00, 499.00,
   '{"email":true,"accounting":true,"ai_briefings":true,"whatsapp_briefing":true,"receptionist":true,"quoting":true,"calendar_booking":true,"premium_support":true}',
   '{"users":20,"businesses":-1}',
   3)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  monthly_price_gbp = EXCLUDED.monthly_price_gbp,
  setup_fee_gbp = EXCLUDED.setup_fee_gbp,
  features = EXCLUDED.features,
  limits = EXCLUDED.limits,
  sort_order = EXCLUDED.sort_order,
  updated_at = now();
