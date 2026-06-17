-- 033_field_name_harmonization.sql
-- Description: Unify field_key values in card_schema to match SPEC v3 canonical naming.
--              Aligns legacy field names with the v3 field manifest used in L3 prompts,
--              extractors, and the entity layer.
-- Date: 2026-06-17
--
-- Mapping summary:
--   company_category        → company_type                (v3 card_schema only)
--   gtm_motion              → gtm_strategy                (v3 card_schema only)
--   differentiation_strategy → differentiated_opportunity (all card sets)
--   tech_stack              → product_tech_stack          (v3 card_schema only)
--
-- Entity table column names (companies.company_category, company_analysis.gtm_motion,
-- products.tech_stack) are NOT altered by this migration — only the card_schema.field_key
-- references that drive the card rendering pipeline are harmonized.  The entity-layer
-- columns are addressed separately.

BEGIN;

-- 1. company_category → company_type (v3 only)
--    SPEC v3 refers to the company classification as 'company_type' throughout.
UPDATE card_schema
   SET field_key = 'company_type'
 WHERE field_key = 'company_category'
   AND card_set_key = 'v3';

-- 2. gtm_motion → gtm_strategy (v3 only)
--    SPEC v3 canonical name is 'gtm_strategy' (gtm_motion was an earlier draft name).
UPDATE card_schema
   SET field_key = 'gtm_strategy'
 WHERE field_key = 'gtm_motion'
   AND card_set_key = 'v3';

-- 3. differentiation_strategy → differentiated_opportunity (all card sets)
--    SPEC v3 renamed this to better capture the asymmetric-positioning intent.
--    'differentiation_strategy' implies generic differentiation,
--    'differentiated_opportunity' identifies specific gaps competitors cannot easily fill.
UPDATE card_schema
   SET field_key = 'differentiated_opportunity'
 WHERE field_key = 'differentiation_strategy';

-- 4. tech_stack → product_tech_stack (v3 only)
--    SPEC v3 uses 'product_tech_stack' to distinguish product-level tech from
--    company-wide infrastructure.  The v3 preset inserts already use
--    'product_tech_stack', but rows inserted by the app at runtime may still
--    carry the shorter legacy key.
UPDATE card_schema
   SET field_key = 'product_tech_stack'
 WHERE field_key = 'tech_stack'
   AND card_set_key = 'v3';

COMMIT;
