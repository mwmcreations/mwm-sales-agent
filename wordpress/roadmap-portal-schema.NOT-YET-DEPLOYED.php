<?php
// Code Snippets plugin — MWM ROADMAP™ Portal · SCHEMA (NOT YET DEPLOYED — no WP snippet ID yet;
// rename to wp-snippet-<ID>-roadmap-schema.php once it is created in wp-admin)
// DEV · Aug 9 2026 · Spec: docs/ROADMAP_Portal_Spec.md
//
// Phase 1 of 7. This snippet creates tables ONLY. It renders nothing, exposes
// no endpoint, and touches no existing table. Safe to activate before any of
// the portal UI exists.
//
// Conventions copied deliberately from the studio portal (snippet 15):
//   · $wpdb->prefix . 'mwm_...' table names
//   · access_code stored as wp_hash_password(), never plaintext
//   · dbDelta() so re-activation is idempotent
//
// 🔑 dbDelta is FUSSY. Two spaces after PRIMARY KEY, one field per line,
//    KEY not INDEX, no backticks on the table name. Do not "tidy" this.

define( 'MWM_ROADMAP_DB_VERSION', '1.0.0' );

function mwm_roadmap_install_schema() {

	global $wpdb;
	require_once ABSPATH . 'wp-admin/includes/upgrade.php';

	$charset = $wpdb->get_charset_collate();
	$p       = $wpdb->prefix;

	// ── clients ──────────────────────────────────────────────────────────
	// One row per ROADMAP contract. A client on BOTH products keeps their
	// studio row too — same email, same access code, two ledgers.
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_clients (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		client_name varchar(191) NOT NULL,
		company varchar(191) DEFAULT '' NOT NULL,
		email varchar(191) NOT NULL,
		access_code varchar(255) NOT NULL,
		plan varchar(20) NOT NULL DEFAULT 'gold',
		campaigns_allowed smallint(5) unsigned NOT NULL DEFAULT 12,
		contract_start date DEFAULT NULL,
		contract_end date DEFAULT NULL,
		strategist varchar(191) DEFAULT '' NOT NULL,
		language varchar(5) NOT NULL DEFAULT 'en',
		stripe_customer_id varchar(64) DEFAULT '' NOT NULL,
		status varchar(20) NOT NULL DEFAULT 'active',
		created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		updated_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		PRIMARY KEY  (id),
		UNIQUE KEY email (email),
		KEY status (status)
	) $charset;";

	// ── campaigns ────────────────────────────────────────────────────────
	// The unit of work. A campaign is a MONTH: one theme, one hero film,
	// N reels cut from the same shoot day.
	//
	// shoot_state is the §6 scheduling machine:
	//   none → pre_scheduled → confirmed        (client picks, MWM confirms)
	//   none → proposed      → confirmed        (MWM proposes, client confirms)
	//   proposed/pre_scheduled → rebooking      (either side pushes back)
	//
	// shoot_kind drives the NOTICE RULE and nothing else:
	//   studio   → 48 hours   ·   location → 7 days
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_campaigns (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		client_id bigint(20) unsigned NOT NULL,
		month_no smallint(5) unsigned NOT NULL,
		title varchar(191) NOT NULL,
		theme_desc text NULL,
		hero_spec varchar(64) DEFAULT '' NOT NULL,
		status varchar(20) NOT NULL DEFAULT 'planned',
		shoot_state varchar(20) NOT NULL DEFAULT 'none',
		shoot_kind varchar(20) DEFAULT NULL,
		shoot_at datetime DEFAULT NULL,
		shoot_end datetime DEFAULT NULL,
		shoot_location varchar(255) DEFAULT '' NOT NULL,
		requested_by varchar(191) DEFAULT '' NOT NULL,
		requested_at datetime DEFAULT NULL,
		hold_expires_at datetime DEFAULT NULL,
		confirmed_by varchar(191) DEFAULT '' NOT NULL,
		confirmed_at datetime DEFAULT NULL,
		gcal_event_id varchar(191) DEFAULT '' NOT NULL,
		delivered_at date DEFAULT NULL,
		sort_order smallint(5) unsigned NOT NULL DEFAULT 0,
		created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		updated_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		PRIMARY KEY  (id),
		UNIQUE KEY client_month (client_id,month_no),
		KEY shoot_state (shoot_state),
		KEY hold_expires_at (hold_expires_at)
	) $charset;";

	// ── assets ───────────────────────────────────────────────────────────
	// review_state is the §5 approval machine, PER ASSET — a month can be
	// half approved:  review → approved  |  review → fix → (revision) → review
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_assets (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		campaign_id bigint(20) unsigned NOT NULL,
		title varchar(191) NOT NULL,
		kind varchar(20) NOT NULL DEFAULT 'hero',
		url text NULL,
		qty smallint(5) unsigned NOT NULL DEFAULT 1,
		duration_secs mediumint(8) unsigned DEFAULT NULL,
		delivered_at datetime DEFAULT NULL,
		review_state varchar(20) NOT NULL DEFAULT 'review',
		revision_no smallint(5) unsigned NOT NULL DEFAULT 1,
		reviewed_by varchar(191) DEFAULT '' NOT NULL,
		reviewed_at datetime DEFAULT NULL,
		sheet_row_key varchar(191) DEFAULT '' NOT NULL,
		created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		updated_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		PRIMARY KEY  (id),
		KEY campaign_id (campaign_id),
		KEY review_state (review_state),
		KEY sheet_row_key (sheet_row_key)
	) $charset;";

	// ── asset events ─────────────────────────────────────────────────────
	// APPEND ONLY. Never UPDATE, never DELETE. review_state on the asset is
	// a cache of the latest row here. When someone asks "who approved this
	// and when", the answer has to exist — including for an email-token tap.
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_asset_events (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		asset_id bigint(20) unsigned NOT NULL,
		event varchar(32) NOT NULL,
		actor varchar(191) NOT NULL,
		actor_kind varchar(20) NOT NULL DEFAULT 'client',
		note text NULL,
		created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		PRIMARY KEY  (id),
		KEY asset_id (asset_id),
		KEY created_at (created_at)
	) $charset;";

	// ── actions ("needs your attention") ─────────────────────────────────
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_actions (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		client_id bigint(20) unsigned NOT NULL,
		campaign_id bigint(20) unsigned DEFAULT NULL,
		title varchar(191) NOT NULL,
		detail text NULL,
		due_date date DEFAULT NULL,
		resolved tinyint(1) NOT NULL DEFAULT 0,
		resolved_at datetime DEFAULT NULL,
		created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		PRIMARY KEY  (id),
		KEY client_open (client_id,resolved)
	) $charset;";

	// ── confirm tokens (§7.5) ────────────────────────────────────────────
	// Single-use HMAC tokens behind the Confirm / Decline buttons in the
	// info@ email. Only the HASH is stored, so a database read cannot
	// confirm a shoot. used_at makes a second tap a no-op, not a re-fire.
	$sql[] = "CREATE TABLE {$p}mwm_roadmap_tokens (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		token_hash char(64) NOT NULL,
		campaign_id bigint(20) unsigned NOT NULL,
		action varchar(20) NOT NULL,
		issued_to varchar(191) NOT NULL,
		expires_at datetime NOT NULL,
		used_at datetime DEFAULT NULL,
		used_ip varchar(45) DEFAULT '' NOT NULL,
		created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
		PRIMARY KEY  (id),
		UNIQUE KEY token_hash (token_hash),
		KEY campaign_id (campaign_id),
		KEY expires_at (expires_at)
	) $charset;";

	foreach ( $sql as $stmt ) {
		dbDelta( $stmt );
	}

	update_option( 'mwm_roadmap_db_version', MWM_ROADMAP_DB_VERSION, false );
}

// Run once per version bump, not on every page load.
add_action( 'init', function () {
	if ( get_option( 'mwm_roadmap_db_version' ) !== MWM_ROADMAP_DB_VERSION ) {
		mwm_roadmap_install_schema();
	}
}, 1 );
