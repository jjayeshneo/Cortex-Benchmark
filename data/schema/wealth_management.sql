-- Cortex-Bench — full DDL for the wealth-management database
-- snapshot: wm_synthetic_v1.2_2026_09_01
-- 22 tables, generated from the live schema. DuckDB dialect.

-- advisor_profile: 117 rows
CREATE TABLE advisor_profile (
    advisor_sk                           BIGINT,
    advisor_code                         VARCHAR,
    advisor_full_name                    VARCHAR,
    advisor_email                        VARCHAR,
    advisor_mobile                       VARCHAR,
    gender                               VARCHAR,
    date_of_birth                        DATE,
    date_joined                          DATE,
    date_exited                          VARCHAR,
    designation                          VARCHAR,
    role_category                        VARCHAR,
    seniority_band                       VARCHAR,
    line_manager_advisor_sk              DOUBLE,
    business_unit_sk                     BIGINT,
    branch_code                          VARCHAR,
    branch_name                          VARCHAR,
    region                               VARCHAR,
    city                                 VARCHAR,
    state                                VARCHAR,
    arn_code                             VARCHAR,
    sebi_ria_code                        VARCHAR,
    revenue_share_pct                    DOUBLE,
    is_active                            BOOLEAN,
    effective_from                       DATE,
    effective_to                         VARCHAR,
    is_current                           BOOLEAN
);

-- instrument_credit_rating: 184 rows
CREATE TABLE instrument_credit_rating (
    rating_sk                            BIGINT,
    instrument_sk                        BIGINT,
    rating_agency                        VARCHAR,
    rating_value                         VARCHAR,
    rating_outlook                       VARCHAR,
    rated_on                             DATE,
    valid_until                          DATE,
    is_current                           BOOLEAN
);

-- instrument_detail: 355 rows
CREATE TABLE instrument_detail (
    instrument_sk                        BIGINT,
    product_family                       VARCHAR,
    company_name                         VARCHAR,
    nse_symbol                           VARCHAR,
    bse_code                             BIGINT,
    market_cap_band                      VARCHAR,
    market_cap_crore                     DOUBLE,
    face_value                           DOUBLE,
    pe_ratio                             DOUBLE,
    dividend_yield                       DOUBLE,
    beta_1y                              DOUBLE,
    f_and_o_eligible                     BOOLEAN,
    issuer_type                          VARCHAR,
    coupon_rate_pct                      DOUBLE,
    coupon_frequency                     VARCHAR,
    issue_date                           DATE,
    maturity_date                        DATE,
    tenor_months                         DOUBLE,
    seniority                            VARCHAR,
    collateral_type                      VARCHAR,
    ytm_pct                              DOUBLE,
    modified_duration_yrs                DOUBLE,
    amc_code                             VARCHAR,
    amc_name                             VARCHAR,
    amfi_scheme_code                     BIGINT,
    scheme_category                      VARCHAR,
    scheme_sub_category                  VARCHAR,
    plan_type                            VARCHAR,
    option_type                          VARCHAR,
    fund_manager_name                    VARCHAR,
    expense_ratio                        DOUBLE,
    exit_load_pct                        DOUBLE,
    exit_load_period_days                DOUBLE,
    aum_crore                            DOUBLE,
    is_etf                               BOOLEAN,
    is_index_fund                        BOOLEAN,
    is_obsolete                          BOOLEAN,
    merged_into_instrument_sk            VARCHAR,
    structure_type                       VARCHAR,
    strategy_name                        VARCHAR,
    manager_name                         VARCHAR,
    lock_in_months_detail                DOUBLE,
    hurdle_rate_pct                      DOUBLE,
    performance_fee_pct                  DOUBLE,
    management_fee_pct                   DOUBLE,
    min_commitment                       DOUBLE
);

-- instrument_master: 355 rows
CREATE TABLE instrument_master (
    instrument_sk                        BIGINT,
    instrument_code                      VARCHAR,
    isin                                 VARCHAR,
    ticker_nse                           VARCHAR,
    ticker_bse                           VARCHAR,
    security_name                        VARCHAR,
    short_name                           VARCHAR,
    product_family                       VARCHAR,
    asset_class_code                     VARCHAR,
    asset_class_name                     VARCHAR,
    sub_asset_class_code                 VARCHAR,
    sub_asset_class_name                 VARCHAR,
    issuer_name                          VARCHAR,
    sector                               VARCHAR,
    industry                             VARCHAR,
    currency_iso3                        VARCHAR,
    listing_status                       VARCHAR,
    primary_exchange                     VARCHAR,
    risk_rating                          VARCHAR,
    lock_in_months                       DOUBLE,
    min_investment                       DOUBLE,
    benchmark_instrument_sk              BIGINT,
    is_active                            BOOLEAN,
    inception_date                       DATE,
    termination_date                     DATE,
    effective_from                       DATE,
    effective_to                         VARCHAR,
    is_current                           BOOLEAN
);

-- investor_account: 18,430 rows
CREATE TABLE investor_account (
    account_sk                           BIGINT,
    account_number                       VARCHAR,
    account_external_ref                 VARCHAR,
    account_type                         VARCHAR,
    account_sub_type                     VARCHAR,
    investor_sk                          BIGINT,
    joint_holder_investor_sk             VARCHAR,
    depository                           VARCHAR,
    dp_id                                VARCHAR,
    folio_or_client_id                   BIGINT,
    custodian_name                       VARCHAR,
    opened_on                            DATE,
    closed_on                            VARCHAR,
    is_active                            BOOLEAN,
    effective_from                       DATE,
    effective_to                         VARCHAR,
    is_current                           BOOLEAN
);

-- investor_goal: 27,244 rows
CREATE TABLE investor_goal (
    goal_sk                              BIGINT,
    investor_sk                          BIGINT,
    goal_name                            VARCHAR,
    goal_category                        VARCHAR,
    target_amount                        DOUBLE,
    target_date                          DATE,
    priority                             VARCHAR,
    linked_account_sk                    DOUBLE,
    created_on                           DATE,
    is_active                            BOOLEAN
);

-- investor_profile: 10,000 rows
CREATE TABLE investor_profile (
    investor_sk                          BIGINT,
    investor_code                        VARCHAR,
    tax_id                               VARCHAR,
    legal_name                           VARCHAR,
    display_name                         VARCHAR,
    investor_type                        VARCHAR,
    gender                               VARCHAR,
    date_of_birth                        DATE,
    date_of_incorporation                DATE,
    residency_status                     VARCHAR,
    occupation                           VARCHAR,
    income_band                          VARCHAR,
    net_worth_band                       VARCHAR,
    marital_status                       VARCHAR,
    kyc_status                           VARCHAR,
    kyc_completed_on                     DATE,
    pep_flag                             BOOLEAN,
    client_segment                       VARCHAR,
    onboarding_date                      DATE,
    offboarding_date                     DATE,
    household_code                       VARCHAR,
    household_name                       VARCHAR,
    household_type                       VARCHAR,
    group_code                           VARCHAR,
    group_name                           VARCHAR,
    group_type                           VARCHAR,
    business_unit_sk                     BIGINT,
    primary_advisor_sk                   BIGINT,
    acquiring_advisor_sk                 BIGINT,
    referral_source                      VARCHAR,
    risk_score                           DOUBLE,
    risk_bucket                          VARCHAR,
    time_horizon_years                   BIGINT,
    target_model_portfolio_sk            BIGINT,
    risk_assessed_on                     DATE,
    aum_inr                              DOUBLE,
    is_active                            BOOLEAN,
    is_deleted                           BOOLEAN,
    effective_from                       DATE,
    effective_to                         VARCHAR,
    is_current                           BOOLEAN
);

-- kpi_advisor_target: 468 rows
CREATE TABLE kpi_advisor_target (
    target_sk                            BIGINT,
    advisor_sk                           BIGINT,
    target_period                        VARCHAR,
    period_start_date                    DATE,
    period_end_date                      DATE,
    target_revenue_inr                   DOUBLE,
    target_aum_inr                       DOUBLE,
    target_nnm_inr                       DOUBLE,
    target_new_clients                   BIGINT,
    target_cross_sell_ratio              DOUBLE,
    set_by_manager_sk                    DOUBLE,
    set_on                               DATE
);

-- market_corporate_action: 35 rows
CREATE TABLE market_corporate_action (
    corp_action_sk                       BIGINT,
    instrument_sk                        BIGINT,
    action_type                          VARCHAR,
    record_date                          DATE,
    ex_date                              DATE,
    payment_date                         DATE,
    ratio_numerator                      DOUBLE,
    ratio_denominator                    DOUBLE,
    dividend_per_share                   DOUBLE,
    merge_into_instrument_sk             VARCHAR,
    narration                            VARCHAR
);

-- market_index_daily: 2,310 rows
CREATE TABLE market_index_daily (
    index_sk                             BIGINT,
    index_code                           VARCHAR,
    index_name                           VARCHAR,
    index_date                           DATE,
    open_value                           DOUBLE,
    high_value                           DOUBLE,
    low_value                            DOUBLE,
    close_value                          DOUBLE,
    total_return_value                   DOUBLE
);

-- market_price_daily: 312,660 rows
CREATE TABLE market_price_daily (
    price_sk                             BIGINT,
    instrument_sk                        BIGINT,
    price_date                           DATE,
    price_type                           VARCHAR,
    open_price                           DOUBLE,
    high_price                           DOUBLE,
    low_price                            DOUBLE,
    close_price                          DOUBLE,
    adj_close_price                      DOUBLE,
    traded_volume                        BIGINT,
    source_system                        VARCHAR
);

-- model_portfolio: 5 rows
CREATE TABLE model_portfolio (
    model_portfolio_sk                   BIGINT,
    model_name                           VARCHAR,
    strategy_type                        VARCHAR,
    target_return_pct                    DOUBLE,
    target_volatility_pct                DOUBLE,
    rebalance_band_pct                   DOUBLE,
    created_on                           DATE,
    is_active                            BOOLEAN
);

-- model_portfolio_allocation: 25 rows
CREATE TABLE model_portfolio_allocation (
    allocation_sk                        BIGINT,
    model_portfolio_sk                   BIGINT,
    asset_class_code                     VARCHAR,
    sub_asset_class_code                 VARCHAR,
    target_weight_pct                    DOUBLE,
    min_weight_pct                       DOUBLE,
    max_weight_pct                       DOUBLE
);

-- org_business_unit: 13 rows
CREATE TABLE org_business_unit (
    business_unit_sk                     BIGINT,
    sbu_code                             VARCHAR,
    sbu_name                             VARCHAR,
    business_line_code                   VARCHAR,
    business_line_name                   VARCHAR,
    sub_line_code                        VARCHAR,
    sub_line_name                        VARCHAR,
    parent_business_unit_sk              DOUBLE,
    cost_centre_code                     VARCHAR,
    is_active                            BOOLEAN,
    effective_from                       DATE,
    effective_to                         VARCHAR,
    is_current                           BOOLEAN
);

-- pos_holding_daily: 52,052,531 rows
CREATE TABLE pos_holding_daily (
    holding_sk                           BIGINT,
    as_of_date                           DATE,
    investor_sk                          BIGINT,
    account_sk                           BIGINT,
    instrument_sk                        BIGINT,
    holding_quantity                     DOUBLE,
    avg_cost_unit                        DOUBLE,
    total_cost_inr                       DOUBLE,
    accrued_interest_inr                 DOUBLE,
    is_held_away                         BOOLEAN,
    lien_marked                          BOOLEAN,
    source_system                        VARCHAR
);

-- pos_holding_lot: 840,592 rows
CREATE TABLE pos_holding_lot (
    lot_sk                               BIGINT,
    investor_sk                          BIGINT,
    account_sk                           BIGINT,
    instrument_sk                        BIGINT,
    acquisition_trade_sk                 BIGINT,
    acquired_on                          DATE,
    acquired_quantity                    DOUBLE,
    acquired_unit_cost                   DOUBLE,
    remaining_quantity                   DOUBLE,
    lot_status                           VARCHAR,
    source_system                        VARCHAR,
    loaded_at_ts                         TIMESTAMP
);

-- rule_taxation: 8 rows
CREATE TABLE rule_taxation (
    rule_sk                              BIGINT,
    asset_class_code                     VARCHAR,
    product_family                       VARCHAR,
    residency_status                     VARCHAR,
    stcg_threshold_days                  BIGINT,
    stcg_tax_rate_pct                    DOUBLE,
    ltcg_tax_rate_pct                    DOUBLE,
    ltcg_exemption_inr                   DOUBLE,
    effective_from                       DATE,
    effective_to                         DATE,
    rule_version                         VARCHAR,
    notes                                VARCHAR
);

-- txn_cashflow: 937,171 rows
CREATE TABLE txn_cashflow (
    cashflow_sk                          BIGINT,
    investor_sk                          BIGINT,
    account_sk                           BIGINT,
    instrument_sk                        BIGINT,
    cashflow_date                        DATE,
    cashflow_type                        VARCHAR,
    cashflow_direction                   VARCHAR,
    amount_inr                           DOUBLE,
    signed_amount_inr                    DOUBLE,
    fee_period_start                     VARCHAR,
    fee_period_end                       VARCHAR,
    fee_status                           VARCHAR,
    linked_trade_sk                      BIGINT,
    linked_corp_action_sk                VARCHAR,
    narration                            VARCHAR,
    source_system                        VARCHAR,
    loaded_at_ts                         TIMESTAMP
);

-- txn_firm_revenue: 3,214,159 rows
CREATE TABLE txn_firm_revenue (
    revenue_sk                           BIGINT,
    revenue_date                         DATE,
    recognition_period                   VARCHAR,
    investor_sk                          BIGINT,
    account_sk                           BIGINT,
    instrument_sk                        BIGINT,
    primary_advisor_sk                   BIGINT,
    acquiring_advisor_sk                 BIGINT,
    business_unit_sk                     BIGINT,
    revenue_type                         VARCHAR,
    revenue_subtype                      VARCHAR,
    product_family                       VARCHAR,
    gross_revenue_inr                    DOUBLE,
    tax_amount_inr                       DOUBLE,
    net_revenue_inr                      DOUBLE,
    advisor_commission_inr               DOUBLE,
    firm_retained_inr                    DOUBLE,
    linked_trade_sk                      DOUBLE
);

-- txn_lot_closure: 107,071 rows
CREATE TABLE txn_lot_closure (
    closure_sk                           BIGINT,
    sell_trade_sk                        BIGINT,
    buy_lot_sk                           BIGINT,
    investor_sk                          BIGINT,
    account_sk                           BIGINT,
    instrument_sk                        BIGINT,
    matched_quantity                     DOUBLE,
    matched_buy_unit_cost                DOUBLE,
    matched_sell_unit_price              DOUBLE,
    acquired_on                          DATE,
    sold_on                              DATE,
    holding_period_days                  BIGINT,
    cost_basis_method                    VARCHAR,
    source_system                        VARCHAR
);

-- txn_sip_mandate: 2,862 rows
CREATE TABLE txn_sip_mandate (
    mandate_sk                           BIGINT,
    investor_sk                          BIGINT,
    account_sk                           BIGINT,
    instrument_sk                        BIGINT,
    mandate_type                         VARCHAR,
    source_instrument_sk                 VARCHAR,
    amount_per_installment               DOUBLE,
    frequency                            VARCHAR,
    start_date                           DATE,
    end_date                             VARCHAR,
    next_run_date                        DATE,
    installments_planned                 BIGINT,
    installments_completed               BIGINT,
    mandate_status                       VARCHAR,
    created_by_advisor_sk                BIGINT
);

-- txn_trade: 937,171 rows
CREATE TABLE txn_trade (
    trade_sk                             BIGINT,
    trade_reference                      VARCHAR,
    investor_sk                          BIGINT,
    account_sk                           BIGINT,
    instrument_sk                        BIGINT,
    trade_date                           DATE,
    settlement_date                      DATE,
    trade_action                         VARCHAR,
    order_type                           VARCHAR,
    quantity                             DOUBLE,
    unit_price                           DOUBLE,
    gross_amount                         DOUBLE,
    brokerage                            DOUBLE,
    stt_amount                           DOUBLE,
    gst_amount                           DOUBLE,
    stamp_duty                           DOUBLE,
    other_charges                        DOUBLE,
    net_amount                           DOUBLE,
    executed_by_advisor_sk               BIGINT,
    broker_code                          VARCHAR,
    exchange                             VARCHAR,
    folio_or_dp_ref                      VARCHAR,
    linked_mandate_sk                    BIGINT,
    is_corrected                         BOOLEAN,
    source_system                        VARCHAR,
    loaded_at_ts                         TIMESTAMP
);
