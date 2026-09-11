<?php
// Code Snippets plugin — MWM ROADMAP™ Portal · SCHEMA v1.3.0
// DEV · Sep 11 2026 · extends v1.2.0 (WP snippet 28)
// Source of truth: MWM_Contrato_Plano_GOLD_MWM-LC-2026-02.pdf Rev 5 · ROB, #dev Sep 11
//
// WHAT CHANGED AND WHY
// v1.2.0 modelled the plan the way the /order/ cards described it: campaigns,
// captures, a pool of studio hours for the year. The signed GOLD agreement is a
// different shape — hours PER BILLING CYCLE that expire, deliveries expressed as
// ceilings, and add-ons that need written approval before anything is booked.
// ROB: "build the portal's entitlement model against this document, not against
// the old /order/ card copy."
//
// 🔴 ADDITIVE ONLY. dbDelta adds the new columns and tables; nothing is dropped,
// nothing is renamed, and the v1.2.0 campaign/capture columns stay exactly where
// they are so Z Brothers and Bolfer keep rendering while GOLD is built alongside.
//
// 🔑 dbDelta is FUSSY. Two spaces after PRIMARY KEY, one field per line,
//    KEY not INDEX, no backticks on the table name. Do not "tidy" this.

if ( ! defined( 'ABSPATH' ) ) { exit; }

define( 'MWM_ROADMAP_DB_VERSION', '1.3.0' );

function mwm_roadmap_install_schema_v130() {

	global $wpdb;
	require_once ABSPATH . 'wp-admin/includes/upgrade.php';

	$charset = $wpdb->get_charset_collate();
	$p       = $wpdb->prefix;
	$sql     = array();

	// ── clients · the contract columns ───────────────────────────────────
	// dbDelta adds columns to an existing table when the full CREATE TABLE is
	// restated, so this block repeats v1.2.0's columns verbatim and appends.
	//
	// billing_anchor_day is the day of the month the card is charged (§4: "na
	// mesma data de cada mês"). The cycle is anchored to it, NOT to the calendar
	// month — a client who signs on the 14th has a cycle running 14th → 13th,
	// and her hours die on the 13th.
	//
	// rate_card_version is the ToS §13 rule made structural: "Pricing changes
	// apply to new subscriptions only." The price is read from the version on
	// THIS row, never from whatever is current.
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_clients (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		client_name varchar(191) NOT NULL,
		company varchar(191) DEFAULT '' NOT NULL,
		email varchar(191) NOT NULL,
		access_code varchar(255) NOT NULL,
		plan varchar(20) NOT NULL DEFAULT 'gold',
		campaigns_allowed smallint(5) unsigned NOT NULL DEFAULT 12,
		captures_allowed smallint(5) unsigned NOT NULL DEFAULT 4,
		studio_hours_allowed decimal(5,2) NOT NULL DEFAULT 12.00,
		conversions_used smallint(5) unsigned NOT NULL DEFAULT 0,
		contract_start date DEFAULT NULL,
		contract_end date DEFAULT NULL,
		strategist varchar(191) DEFAULT '' NOT NULL,
		language varchar(5) NOT NULL DEFAULT 'en',
		stripe_customer_id varchar(64) DEFAULT '' NOT NULL,
		studio_client_id bigint(20) unsigned DEFAULT NULL,
		status varchar(20) NOT NULL DEFAULT 'active',
		contract_ref varchar(64) DEFAULT '' NOT NULL,
		rate_card_version varchar(20) DEFAULT '' NOT NULL,
		travel_policy_version varchar(20) DEFAULT '' NOT NULL,
		billing_anchor_day tinyint(3) unsigned DEFAULT NULL,
		billing_mode varchar(20) NOT NULL DEFAULT 'monthly',
		monthly_cents int(10) unsigned DEFAULT NULL,
		term_months smallint(5) unsigned NOT NULL DEFAULT 12,
		included_location_hours decimal(5,2) NOT NULL DEFAULT 0.00,
		included_studio_hours decimal(5,2) NOT NULL DEFAULT 0.00,
		editing_waived tinyint(1) NOT NULL DEFAULT 0,
		primary_contact varchar(191) DEFAULT '' NOT NULL,
		created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		updated_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		PRIMARY KEY  (id),
		UNIQUE KEY email (email),
		KEY status (status)
	) $charset;";

	// ── cycles · where the no-rollover rule actually lives ───────────────
	// 🔴 One row per client per billing cycle. Hours are consumed against the
	// row for the cycle they fall in, so "não cumulativas" is a FACT OF THE
	// SCHEMA rather than a rendering choice. There is no column to carry a
	// balance forward, and that is deliberate — ROB named carry-over, banking
	// and grace periods and ruled out all three. Do not add one.
	//
	// The included_* figures are COPIED onto the cycle at open time, not read
	// from the client row, so a mid-term plan change cannot silently rewrite
	// what a past cycle was worth.
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_cycles (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		client_id bigint(20) unsigned NOT NULL,
		cycle_start date NOT NULL,
		cycle_end date NOT NULL,
		included_location_hours decimal(5,2) NOT NULL DEFAULT 0.00,
		included_studio_hours decimal(5,2) NOT NULL DEFAULT 0.00,
		used_location_hours decimal(5,2) NOT NULL DEFAULT 0.00,
		used_studio_hours decimal(5,2) NOT NULL DEFAULT 0.00,
		rate_card_version varchar(20) DEFAULT '' NOT NULL,
		invoice_ref varchar(64) DEFAULT '' NOT NULL,
		closed_at datetime DEFAULT NULL,
		created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		PRIMARY KEY  (id),
		UNIQUE KEY client_cycle (client_id,cycle_start),
		KEY client_id (client_id)
	) $charset;";

	// ── hour ledger · every hour has a reason and a cycle ────────────────
	// An aggregate you cannot explain is an aggregate a client will dispute.
	// source: 'included' | 'addon'. kind: 'location' | 'studio'.
	// counts_from records the §1 rule in the row itself — hours start on crew
	// ARRIVAL, so a row that was measured some other way is visible as such.
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_hour_entries (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		client_id bigint(20) unsigned NOT NULL,
		cycle_id bigint(20) unsigned NOT NULL,
		campaign_id bigint(20) unsigned DEFAULT NULL,
		addon_id bigint(20) unsigned DEFAULT NULL,
		kind varchar(20) NOT NULL,
		source varchar(20) NOT NULL DEFAULT 'included',
		hours decimal(5,2) NOT NULL DEFAULT 0.00,
		occurred_on date DEFAULT NULL,
		counts_from varchar(40) NOT NULL DEFAULT 'crew_arrival',
		note text NULL,
		created_by varchar(191) DEFAULT '' NOT NULL,
		created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		PRIMARY KEY  (id),
		KEY client_cycle (client_id,cycle_id),
		KEY addon_id (addon_id)
	) $charset;";

	// ── add-ons · requested → approved → scheduled → delivered → billed ──
	// 🔴 approved_by and approved_at are the whole point. "Mediante aprovação
	// prévia por escrito" — the record is what we rely on if it is disputed, so
	// the state cannot be reached without it (enforced in entitlement.php and
	// again at the write site). approval_evidence keeps the actual words: the
	// email, the portal click, the message. A timestamp with no text is thin.
	//
	// unit_cents is STAMPED at approval from the client's own rate card. It is
	// never recomputed later — that is how a signed price stays signed.
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_addons (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		client_id bigint(20) unsigned NOT NULL,
		cycle_id bigint(20) unsigned DEFAULT NULL,
		campaign_id bigint(20) unsigned DEFAULT NULL,
		code varchar(40) NOT NULL,
		label varchar(191) DEFAULT '' NOT NULL,
		qty decimal(6,2) NOT NULL DEFAULT 1.00,
		unit_cents int(10) unsigned DEFAULT NULL,
		total_cents int(10) unsigned DEFAULT NULL,
		rate_card_version varchar(20) DEFAULT '' NOT NULL,
		travel_zone tinyint(3) unsigned DEFAULT NULL,
		travel_miles decimal(6,1) DEFAULT NULL,
		travel_fee_cents int(10) unsigned DEFAULT NULL,
		state varchar(20) NOT NULL DEFAULT 'requested',
		requested_by varchar(191) DEFAULT '' NOT NULL,
		requested_at datetime DEFAULT NULL,
		approved_by varchar(191) DEFAULT NULL,
		approved_at datetime DEFAULT NULL,
		approval_evidence text NULL,
		declined_reason text NULL,
		scheduled_for datetime DEFAULT NULL,
		delivered_at date DEFAULT NULL,
		billed_on date DEFAULT NULL,
		invoice_ref varchar(64) DEFAULT '' NOT NULL,
		notes text NULL,
		created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		updated_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		PRIMARY KEY  (id),
		KEY client_state (client_id,state),
		KEY cycle_id (cycle_id)
	) $charset;";

	// ── add-on events · append-only, never updated ───────────────────────
	// Same posture as roadmap_asset_events. When someone asks "who approved
	// this and when", the answer must exist and must not have been overwritten.
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_addon_events (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		addon_id bigint(20) unsigned NOT NULL,
		event varchar(30) NOT NULL,
		actor varchar(191) DEFAULT '' NOT NULL,
		from_state varchar(20) DEFAULT '' NOT NULL,
		to_state varchar(20) DEFAULT '' NOT NULL,
		note text NULL,
		created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		PRIMARY KEY  (id),
		KEY addon_id (addon_id)
	) $charset;";

	// ── rate cards · the data half of "never hardcoded" ──────────────────
	// A new year's prices are a row, not a deploy. Existing clients keep the
	// version stamped on their own row (ToS §13).
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_rate_cards (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		version varchar(20) NOT NULL,
		effective_on date DEFAULT NULL,
		contract_ref varchar(64) DEFAULT '' NOT NULL,
		currency varchar(8) NOT NULL DEFAULT 'USD',
		notes text NULL,
		created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		PRIMARY KEY  (id),
		UNIQUE KEY version (version)
	) $charset;";

	// annual_cents = 0 with waived = 1 is the editing line: genuinely free on
	// the annual plan. A NULL price means NOT OFFERED on that basis — the
	// distinction matters, because falling through to zero gives work away.
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_rate_card_items (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		version varchar(20) NOT NULL,
		code varchar(40) NOT NULL,
		label varchar(191) NOT NULL,
		unit varchar(20) NOT NULL DEFAULT 'hour',
		standalone_cents int(10) unsigned DEFAULT NULL,
		annual_cents int(10) unsigned DEFAULT NULL,
		waived_on_annual tinyint(1) NOT NULL DEFAULT 0,
		ceiling_main_videos smallint(5) unsigned DEFAULT NULL,
		ceiling_episodes smallint(5) unsigned DEFAULT NULL,
		ceiling_shorts smallint(5) unsigned DEFAULT NULL,
		note text NULL,
		sort_order smallint(5) unsigned NOT NULL DEFAULT 0,
		PRIMARY KEY  (id),
		UNIQUE KEY version_code (version,code)
	) $charset;";

	// ── travel zones · one table, every client ───────────────────────────
	// ROB: "This table is identical for every client. Same source, one place in
	// the DB." fee_cents NULL + quote_only = zone 5. Never 0.
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_travel_zones (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		version varchar(20) NOT NULL DEFAULT 'v1.1',
		zone tinyint(3) unsigned NOT NULL,
		min_mi smallint(5) unsigned NOT NULL DEFAULT 0,
		max_mi smallint(5) unsigned DEFAULT NULL,
		fee_cents int(10) unsigned DEFAULT NULL,
		included tinyint(1) NOT NULL DEFAULT 0,
		quote_only tinyint(1) NOT NULL DEFAULT 0,
		label varchar(191) DEFAULT '' NOT NULL,
		PRIMARY KEY  (id),
		UNIQUE KEY version_zone (version,zone)
	) $charset;";

	foreach ( $sql as $stmt ) {
		dbDelta( $stmt );
	}

	update_option( 'mwm_roadmap_db_version', MWM_ROADMAP_DB_VERSION, false );
}

add_action( 'init', function () {
	if ( get_option( 'mwm_roadmap_db_version' ) !== MWM_ROADMAP_DB_VERSION ) {
		mwm_roadmap_install_schema_v130();
	}
}, 1 );
