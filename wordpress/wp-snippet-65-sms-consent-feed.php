<?php
// SMS CONSENT FEED — reads wp_mwm_sms_consent for the Sales Machine
// DEV · Aug 27 2026 · Patch #109 · companion to sms_consent.py
//
// ─────────────────────────────────────────────────────────────────────────────
// WHY THIS EXISTS
//
// The A2P campaign was approved on Aug 27 after five weeks and eight
// submissions. The whole point of that fight was SMS re-engagement — and on
// the day it was approved, nothing could send, because consent lived here and
// the gate that reads consent lives on Railway.
//
// The opt-in form at /sms-signup/ writes into wp_mwm_sms_consent (see
// snippet-a2p-optin-form-v1.1). This exposes that table, read-only, to one
// caller holding the same shared secret the studio provisioning endpoint
// already uses. The app polls it every 15 minutes.
//
// READ-ONLY ON PURPOSE. This endpoint can never create, alter or revoke a
// consent — the ledger is the customer's record of what they agreed to, and
// the only things that write to it are the two forms the customer submits.
// ─────────────────────────────────────────────────────────────────────────────

if ( ! defined( 'ABSPATH' ) ) { exit; }

define( 'MWM_SMS_CONSENT_FEED_V', '1.0.0' );

add_action( 'wp_ajax_nopriv_mwm_sms_consent_since', 'mwm_sms_consent_since' );
add_action( 'wp_ajax_mwm_sms_consent_since',        'mwm_sms_consent_since' );

function mwm_sms_consent_since() {

	// Same shared secret as the provisioning endpoint (snippet 15).
	$given    = isset( $_SERVER['HTTP_X_MWM_PORTAL_SECRET'] ) ? $_SERVER['HTTP_X_MWM_PORTAL_SECRET'] : '';
	$expected = get_option( 'mwm_portal_provision_secret', '' );
	if ( ! $expected || ! hash_equals( $expected, $given ) ) {
		wp_send_json_error( array( 'error' => 'unauthorized' ), 403 );
	}

	global $wpdb;
	$table = function_exists( 'mwm_a2p_table' ) ? mwm_a2p_table() : $wpdb->prefix . 'mwm_sms_consent';

	// The caller sends a unix timestamp. It already subtracts an hour of lag on
	// its side and de-duplicates by timestamp, so overlap here is harmless and
	// a gap is not — when in doubt, return more.
	$since = isset( $_POST['since'] ) ? absint( $_POST['since'] ) : 0;
	$since_sql = $since > 0 ? gmdate( 'Y-m-d H:i:s', $since ) : '1970-01-01 00:00:00';

	// Cap the page so a first-run backfill of a large ledger cannot time out.
	// The caller advances its watermark to the newest row it received, so the
	// next poll continues from there rather than starting over.
	$rows = $wpdb->get_results(
		$wpdb->prepare(
			"SELECT phone, phone_e164, transactional, marketing, source_url, created_at
			   FROM {$table}
			  WHERE created_at >= %s
			  ORDER BY created_at ASC
			  LIMIT 500",
			$since_sql
		),
		ARRAY_A
	);

	if ( null === $rows ) {
		wp_send_json_error( array( 'error' => 'query_failed' ), 500 );
	}

	$out = array();
	foreach ( $rows as $r ) {
		$out[] = array(
			// phone_e164 is what the form already normalised; raw phone is
			// sent too so the caller can fall back if an old row lacks it.
			'phone_e164'    => isset( $r['phone_e164'] ) ? $r['phone_e164'] : '',
			'phone'         => isset( $r['phone'] ) ? $r['phone'] : '',
			'transactional' => isset( $r['transactional'] ) ? (int) $r['transactional'] : 0,
			'marketing'     => isset( $r['marketing'] ) ? (int) $r['marketing'] : 0,
			'source'        => 'form',
			'source_url'    => isset( $r['source_url'] ) ? $r['source_url'] : '',
			// created_at is written with gmdate() — UTC. The caller parses
			// it as UTC explicitly; do not "helpfully" localise it here.
			'ts'            => isset( $r['created_at'] ) ? $r['created_at'] : '',
		);
	}

	wp_send_json_success( array(
		'v'     => MWM_SMS_CONSENT_FEED_V,
		'since' => $since_sql,
		'count' => count( $out ),
		'rows'  => $out,
	) );
}
