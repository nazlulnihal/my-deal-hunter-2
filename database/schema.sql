-- =============================================================================
-- DEAL SNIPER — SUPABASE POSTGRESQL & SQLITE COMPATIBLE SCHEMA
-- Enforces Soft-Delete vs Explicit Purge so historical price observations
-- are NEVER lost when a shopping interest is deleted.
-- =============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    id TEXT PRIMARY KEY DEFAULT 'owner_default',
    owner_name TEXT NOT NULL DEFAULT 'Alex (Parramatta NSW)',
    country TEXT NOT NULL DEFAULT 'AU',
    currency TEXT NOT NULL DEFAULT 'AUD',
    preferred_postcodes TEXT NOT NULL DEFAULT '["2150", "2000", "2121"]',
    preferred_suburbs TEXT NOT NULL DEFAULT '["Parramatta", "Sydney CBD", "Epping"]',
    preferred_retailers TEXT NOT NULL DEFAULT '["Officeworks", "JB Hi-Fi", "Amazon Australia", "The Good Guys", "Woolworths", "Coles", "Chemist Warehouse", "Bunnings", "Big W"]',
    include_refurbished_default INTEGER NOT NULL DEFAULT 0,
    min_deal_score_wishlist INTEGER NOT NULL DEFAULT 72,
    min_deal_score_outside INTEGER NOT NULL DEFAULT 90,
    daily_summary_time_aest TEXT NOT NULL DEFAULT '18:00',
    quiet_hours_start TEXT NOT NULL DEFAULT '22:30',
    quiet_hours_end TEXT NOT NULL DEFAULT '07:00',
    ai_provider TEXT NOT NULL DEFAULT 'gemini_flash_free',
    telegram_owner_user_id TEXT NOT NULL DEFAULT '',
    telegram_chat_id TEXT NOT NULL DEFAULT '',
    telegram_mode TEXT NOT NULL DEFAULT 'hybrid_webhook_and_action_poll',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    brand TEXT NOT NULL,
    model_number TEXT,
    barcode_ean_upc TEXT UNIQUE,
    mpn TEXT,
    generation TEXT DEFAULT 'Current Gen',
    category TEXT NOT NULL,
    subcategory TEXT,
    variant_signature TEXT NOT NULL,
    specs_json TEXT NOT NULL DEFAULT '{}',
    pack_quantity REAL NOT NULL DEFAULT 1.0,
    unit_measure TEXT NOT NULL DEFAULT 'item',
    normal_market_price_aud REAL NOT NULL,
    lifecycle_stage TEXT NOT NULL DEFAULT 'current',
    successor_model TEXT,
    image_key TEXT DEFAULT 'tech_watch_phone',
    exact_product_url TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shopping_interests (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    natural_query TEXT NOT NULL,
    interest_type TEXT NOT NULL CHECK(interest_type IN ('exact', 'multiple', 'broad')),
    added_method TEXT NOT NULL DEFAULT 'natural_language' CHECK(added_method IN ('natural_language', 'barcode_scan', 'url_paste', 'telegram_command')),
    scanned_barcode TEXT,
    category TEXT NOT NULL,
    preferred_brands TEXT NOT NULL DEFAULT '[]',
    excluded_brands TEXT NOT NULL DEFAULT '[]',
    max_budget_aud REAL,
    target_price_aud REAL,
    include_refurbished INTEGER NOT NULL DEFAULT 0,
    acceptable_conditions TEXT NOT NULL DEFAULT '["New"]',
    preferred_postcodes TEXT NOT NULL DEFAULT '["2150", "2000"]',
    shortlist_json TEXT NOT NULL DEFAULT '[]',
    priority TEXT NOT NULL DEFAULT 'high' CHECK(priority IN ('critical', 'high', 'normal', 'low')),
    monitoring_frequency_mins INTEGER NOT NULL DEFAULT 15,
    lifecycle_status TEXT NOT NULL DEFAULT 'Exploring' CHECK(lifecycle_status IN (
        'Exploring', 'Researching', 'Waiting for a better price',
        'Ready to purchase', 'Purchased', 'Paused', 'Archived'
    )),
    recorded_purchase_price_aud REAL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_observations (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    retailer TEXT NOT NULL,
    seller_name TEXT NOT NULL,
    is_marketplace INTEGER NOT NULL DEFAULT 0,
    listed_price_aud REAL NOT NULL,
    shipping_cost_aud REAL NOT NULL DEFAULT 0.0,
    coupon_code TEXT,
    coupon_discount_aud REAL NOT NULL DEFAULT 0.0,
    condition TEXT NOT NULL DEFAULT 'New' CHECK(condition IN ('New', 'Refurbished', 'Open-Box', 'Used')),
    stock_badge TEXT NOT NULL DEFAULT 'In Stock Online' CHECK(stock_badge IN (
        'In Stock Online', 'Available Locally for Click & Collect', 'Low Stock', 'Out of Stock'
    )),
    local_postcode_stock_json TEXT NOT NULL DEFAULT '{}',
    price_stage TEXT NOT NULL DEFAULT 'retailer_listed' CHECK(price_stage IN ('search_result', 'retailer_listed', 'checkout_verified')),
    exact_product_url TEXT NOT NULL,
    data_confidence REAL NOT NULL DEFAULT 0.95,
    second_source_verified INTEGER NOT NULL DEFAULT 0,
    is_sample_data INTEGER NOT NULL DEFAULT 0,
    observed_at TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS evaluated_deals (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    interest_id TEXT,
    engine_type TEXT NOT NULL CHECK(engine_type IN ('Engine A', 'Engine B')),
    title TEXT NOT NULL,
    retailer TEXT NOT NULL,
    condition TEXT NOT NULL DEFAULT 'New',
    listed_price_aud REAL NOT NULL,
    shipping_cost_aud REAL NOT NULL DEFAULT 0.0,
    final_checkout_cost_aud REAL NOT NULL,
    normal_market_price_aud REAL NOT NULL,
    median_90d_price_aud REAL NOT NULL,
    lowest_90d_price_aud REAL NOT NULL,
    next_cheapest_competitor_aud REAL NOT NULL,
    discount_vs_median_pct REAL NOT NULL,
    cross_retailer_gap_pct REAL NOT NULL,
    unit_price_display TEXT NOT NULL,
    deal_score INTEGER NOT NULL,
    classification TEXT NOT NULL CHECK(classification IN ('Exceptional', 'Excellent', 'Good', 'Ordinary')),
    rubric_breakdown_json TEXT NOT NULL DEFAULT '{}',
    attractiveness_score INTEGER NOT NULL,
    suitability_score INTEGER NOT NULL,
    seller_trust_score INTEGER NOT NULL,
    data_confidence_score INTEGER NOT NULL,
    availability_score INTEGER NOT NULL,
    stock_badge TEXT NOT NULL,
    local_postcode_summary TEXT NOT NULL,
    is_actionable INTEGER NOT NULL DEFAULT 1,
    is_error_price_anomaly INTEGER NOT NULL DEFAULT 0,
    second_source_status TEXT NOT NULL DEFAULT 'Not Required',
    verification_status TEXT NOT NULL,
    risk_warnings_json TEXT NOT NULL DEFAULT '[]',
    buy_wait_verdict TEXT NOT NULL CHECK(buy_wait_verdict IN ('Buy', 'Consider', 'Wait')),
    buy_wait_reasoning TEXT NOT NULL,
    exact_product_url TEXT NOT NULL,
    is_sample_data INTEGER NOT NULL DEFAULT 0,
    discovered_at TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS supermarket_specials (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    supermarket TEXT NOT NULL CHECK(supermarket IN ('Woolworths', 'Coles')),
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    pack_size_label TEXT NOT NULL,
    normal_price_aud REAL NOT NULL,
    special_price_aud REAL NOT NULL,
    discount_pct REAL NOT NULL,
    unit_price_display TEXT NOT NULL,
    is_half_price INTEGER NOT NULL DEFAULT 0,
    matches_watchlist INTEGER NOT NULL DEFAULT 0,
    matched_interest_name TEXT,
    popularity_rank INTEGER NOT NULL DEFAULT 50,
    stock_badge TEXT NOT NULL DEFAULT 'Available Locally for Click & Collect',
    exact_product_url TEXT NOT NULL,
    is_sample_data INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications_log (
    id TEXT PRIMARY KEY,
    deal_id TEXT,
    notification_type TEXT NOT NULL CHECK(notification_type IN ('immediate_alert', 'daily_6pm_summary', 'command_reply')),
    title TEXT NOT NULL,
    message_body TEXT NOT NULL,
    exact_product_url TEXT,
    status TEXT NOT NULL CHECK(status IN ('sent', 'pending_quiet_hours', 'suppressed_duplicate', 'suppressed_threshold', 'blocked_unauthorised')),
    dedup_signature TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shopping_baskets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    postcode TEXT NOT NULL DEFAULT '2150',
    items_json TEXT NOT NULL,
    last_comparison_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS worker_health (
    worker_id TEXT PRIMARY KEY,
    worker_name TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    interval_mins INTEGER NOT NULL,
    last_successful_run TEXT,
    next_scheduled_run TEXT,
    last_price_collection_at TEXT,
    failed_connectors_json TEXT NOT NULL DEFAULT '[]',
    pending_notifications_count INTEGER NOT NULL DEFAULT 0,
    db_backend_status TEXT NOT NULL DEFAULT 'Connected',
    status TEXT NOT NULL DEFAULT 'healthy',
    run_count INTEGER NOT NULL DEFAULT 0
);

-- Note for Supabase PostgreSQL Deployment:
-- Enable Row Level Security (RLS) on all tables so anon browser keys cannot mutate data:
-- ALTER TABLE shopping_interests ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE products ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE price_observations ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE evaluated_deals ENABLE ROW LEVEL SECURITY;
