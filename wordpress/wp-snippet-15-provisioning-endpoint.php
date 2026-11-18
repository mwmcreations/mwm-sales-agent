<?php
// Code Snippets plugin — Snippet ID 15 (ACTIVE) — reconstructed snapshot Jul 6 2026
// NOTE: live copy bootstraps option mwm_portal_provision_secret with the shared
// secret (REDACTED here — value lives in WP options + Railway env WP_PORTAL_SECRET).

// MWM Studio Portal — Machine Provisioning Endpoint (S7, added by DEV Jul 5 2026)
// Called by the Sales Machine's Stripe webhook. Auth: X-MWM-Portal-Secret header.
// Idempotent by email: existing clients are never duplicated or overwritten.

if ( ! get_option( 'mwm_portal_provision_secret' ) ) {
	update_option( 'mwm_portal_provision_secret', '<REDACTED — see WP option / Railway env>', false );
}

add_action( 'wp_ajax_nopriv_mwm_studio_provision_client', 'mwm_s7_provision_client' );
add_action( 'wp_ajax_mwm_studio_provision_client', 'mwm_s7_provision_client' );

function mwm_s7_gen_access_code() {
	$chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // no 0/O/1/I — 6 chars, matches portal login input maxlength=6
	$code  = '';
	for ( $i = 0; $i < 6; $i++ ) {
		$code .= $chars[ random_int( 0, strlen( $chars ) - 1 ) ];
	}
	return $code;
}

function mwm_s7_provision_client() {
	$given    = isset( $_SERVER['HTTP_X_MWM_PORTAL_SECRET'] ) ? $_SERVER['HTTP_X_MWM_PORTAL_SECRET'] : '';
	$expected = get_option( 'mwm_portal_provision_secret', '' );
	if ( ! $expected || ! hash_equals( $expected, $given ) ) {
		wp_send_json_error( array( 'error' => 'unauthorized' ), 401 );
	}

	global $wpdb;
	$table = $wpdb->prefix . 'mwm_studio_clients';

	$email = isset( $_POST['email'] ) ? strtolower( sanitize_email( wp_unslash( $_POST['email'] ) ) ) : '';
	$name  = isset( $_POST['name'] ) ? sanitize_text_field( wp_unslash( $_POST['name'] ) ) : '';
	if ( ! $email || ! is_email( $email ) ) {
		wp_send_json_error( array( 'error' => 'invalid email' ), 400 );
	}

	$dry      = isset( $_POST['dry_run'] ) && '1' === $_POST['dry_run'];
	$existing = $wpdb->get_row( $wpdb->prepare( "SELECT id, active FROM $table WHERE LOWER(email) = %s", $email ) );

	if ( $existing ) {
		if ( ! $dry && isset( $_POST['rotate_code'] ) && '1' === $_POST['rotate_code'] ) {
			$code = mwm_s7_gen_access_code();
			$wpdb->update( $table,
				array( 'access_code' => wp_hash_password( $code ), 'active' => 1, 'updated_at' => current_time( 'mysql' ) ),
				array( 'id' => $existing->id ) );
			wp_send_json_success( array( 'existing' => true, 'access_code' => $code, 'client_id' => (int) $existing->id ) );
		}
		wp_send_json_success( array( 'existing' => true, 'access_code' => null, 'client_id' => (int) $existing->id, 'dry_run' => $dry ) );
	}

	if ( $dry ) {
		wp_send_json_success( array( 'existing' => false, 'dry_run' => true, 'would_create' => $email ) );
	}

	$code  = mwm_s7_gen_access_code();
	$hours = isset( $_POST['contract_hours'] ) ? max( 1, intval( $_POST['contract_hours'] ) ) : 12;
	$start = isset( $_POST['contract_start'] ) ? sanitize_text_field( wp_unslash( $_POST['contract_start'] ) ) : current_time( 'Y-m-d' );
	$end   = isset( $_POST['contract_end'] ) ? sanitize_text_field( wp_unslash( $_POST['contract_end'] ) ) : date( 'Y-m-d', strtotime( $start . ' +120 days' ) ) /* S8.6: 90d term + 30d grace — matches studio_package.py; machine normally sends contract_end */;

	$ok = $wpdb->insert( $table, array(
		'name'                => $name ? $name : $email,
		'email'               => $email,
		'phone'               => isset( $_POST['phone'] ) ? sanitize_text_field( wp_unslash( $_POST['phone'] ) ) : '',
		'company'             => isset( $_POST['company'] ) ? sanitize_text_field( wp_unslash( $_POST['company'] ) ) : '',
		'access_code'         => wp_hash_password( $code ),
		// PATCH #278 — the plan's own monthly hours (AI Starter is 2, not 4).
		'monthly_hours'       => isset( $_POST['monthly_hours'] ) ? max( 0, (float) $_POST['monthly_hours'] ) : 4,
		'contract_hours'      => $hours,
		'contract_start_date' => $start,
		'contract_end_date'   => $end,
		'package_name'        => isset( $_POST['package'] ) ? sanitize_text_field( wp_unslash( $_POST['package'] ) ) : 'Studio Package',
		'active'              => 1,
		'notes'               => 'Auto-provisioned by Sales Machine (Stripe webhook)',
		'created_at'          => current_time( 'mysql' ),
	) );

	if ( false === $ok ) {
		wp_send_json_error( array( 'error' => 'db insert failed' ), 500 );
	}
	wp_send_json_success( array( 'existing' => false, 'access_code' => $code, 'client_id' => (int) $wpdb->insert_id ) );
}


// ── S7.5: read-only client+hours list for the Sales Machine (canvas/artifact) ──
// Michael authorized Jul 5 2026. Same shared-secret auth as provisioning above.
add_action( 'wp_ajax_nopriv_mwm_studio_list_clients', 'mwm_s7_list_clients' );
add_action( 'wp_ajax_mwm_studio_list_clients', 'mwm_s7_list_clients' );
function mwm_s7_list_clients() {
	$given    = isset( $_SERVER['HTTP_X_MWM_PORTAL_SECRET'] ) ? $_SERVER['HTTP_X_MWM_PORTAL_SECRET'] : '';
	$expected = get_option( 'mwm_portal_provision_secret', '' );
	if ( ! $expected || ! hash_equals( $expected, $given ) ) {
		wp_send_json_error( array( 'error' => 'unauthorized' ), 401 );
	}
	global $wpdb;
	$ct = $wpdb->prefix . 'mwm_studio_clients';
	$bt = $wpdb->prefix . 'mwm_studio_bookings';
	$rows = $wpdb->get_results(
		"SELECT c.id, c.name, c.email, c.package_name, c.contract_hours, c.monthly_hours,
		        c.contract_start_date, c.contract_end_date, c.active,
		        COALESCE( SUM( CASE WHEN b.status IS NULL OR b.status NOT IN ('cancelled','canceled') THEN b.duration_hours ELSE 0 END ), 0 ) AS hours_used
		 FROM $ct c LEFT JOIN $bt b ON b.client_id = c.id
		 GROUP BY c.id ORDER BY c.active DESC, c.contract_end_date ASC", ARRAY_A );
	wp_send_json_success( array( 'clients' => $rows, 'generated_at' => current_time( 'mysql' ) ) );
}

// ── PATCH #278: top up an existing client's hours (Sales Machine) ──
// Michael, Mon 9 Nov 2026: the four plans on /book-studio must be aligned with
// the system. Monthly plans roll unused hours over, capped at 2 months' worth;
// a one-time service adds 1 hour per item, bookable for 60 days.
// POST: email, add_hours, cap_hours (0 = no cap: the client may hold at most
// cap_hours AVAILABLE after this), contract_end (Y-m-d, only ever moves later),
// ref (idempotency: the same ref is applied once), package, monthly_hours,
// dry_run. "Available" is counted exactly like the portal does
// (hours_used_in_contract: confirmed, completed, cancelled_late inside the
// contract window). A client whose window has already closed starts fresh
// today: old, expired hours are not revived by a new purchase.
add_action( 'wp_ajax_nopriv_mwm_studio_topup_client', 'mwm_s7_topup_client' );
add_action( 'wp_ajax_mwm_studio_topup_client', 'mwm_s7_topup_client' );
function mwm_s7_topup_client() {
	$given    = isset( $_SERVER['HTTP_X_MWM_PORTAL_SECRET'] ) ? $_SERVER['HTTP_X_MWM_PORTAL_SECRET'] : '';
	$expected = get_option( 'mwm_portal_provision_secret', '' );
	if ( ! $expected || ! hash_equals( $expected, $given ) ) {
		wp_send_json_error( array( 'error' => 'unauthorized' ), 401 );
	}
	global $wpdb;
	$ct = $wpdb->prefix . 'mwm_studio_clients';
	$bt = $wpdb->prefix . 'mwm_studio_bookings';

	$email = isset( $_POST['email'] ) ? strtolower( sanitize_email( wp_unslash( $_POST['email'] ) ) ) : '';
	if ( ! $email || ! is_email( $email ) ) {
		wp_send_json_error( array( 'error' => 'invalid email' ), 400 );
	}
	$add = isset( $_POST['add_hours'] ) ? (float) $_POST['add_hours'] : 0;
	$cap = isset( $_POST['cap_hours'] ) ? max( 0, (float) $_POST['cap_hours'] ) : 0;
	if ( $add <= 0 || $add > 200 ) {
		wp_send_json_error( array( 'error' => 'add_hours must be between 0 and 200' ), 400 );
	}
	$ref = isset( $_POST['ref'] ) ? substr( sanitize_text_field( wp_unslash( $_POST['ref'] ) ), 0, 120 ) : '';
	$dry = isset( $_POST['dry_run'] ) && '1' === $_POST['dry_run'];

	$c = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM $ct WHERE LOWER(email) = %s", $email ) );
	if ( ! $c ) {
		wp_send_json_success( array( 'found' => false ) );
	}
	$refs = get_option( 'mwm_portal_topup_refs', array() );
	if ( ! is_array( $refs ) ) {
		$refs = array();
	}
	if ( $ref && isset( $refs[ $ref ] ) ) {
		wp_send_json_success( array( 'found' => true, 'duplicate' => true, 'client_id' => (int) $c->id ) );
	}

	$today     = current_time( 'Y-m-d' );
	$end_in    = isset( $_POST['contract_end'] ) ? sanitize_text_field( wp_unslash( $_POST['contract_end'] ) ) : '';
	$end_in    = preg_match( '/^\d{4}-\d{2}-\d{2}$/', $end_in ) ? $end_in : '';
	$old_start = $c->contract_start_date;
	$old_end   = $c->contract_end_date;
	$fresh     = ( ! $old_end || $old_end < $today );
	$start     = $fresh ? $today : $old_start;
	$before    = $fresh ? 0.0 : (float) $c->contract_hours;
	$end       = $old_end;
	if ( $fresh ) {
		$end = $end_in ? $end_in : date( 'Y-m-d', strtotime( $today . ' +60 days' ) );
	} elseif ( $end_in && $end_in > (string) $old_end ) {
		$end = $end_in;
	}
	$used = (float) $wpdb->get_var( $wpdb->prepare(
		"SELECT COALESCE(SUM(duration_hours),0) FROM $bt WHERE client_id = %d
		 AND status IN ('confirmed','completed','cancelled_late')
		 AND booking_date >= %s AND booking_date <= %s",
		$c->id, $start, $end ) );
	$after = $before + $add;
	if ( $cap > 0 ) {
		$after = min( $after, max( $before, $used + $cap ) );
	}
	$after = round( $after, 2 );
	$row   = array( 'contract_hours' => $after, 'contract_start_date' => $start,
	                'contract_end_date' => $end, 'active' => 1, 'updated_at' => current_time( 'mysql' ) );
	if ( isset( $_POST['package'] ) && '' !== trim( (string) $_POST['package'] ) ) {
		$row['package_name'] = sanitize_text_field( wp_unslash( $_POST['package'] ) );
	}
	if ( isset( $_POST['monthly_hours'] ) && (float) $_POST['monthly_hours'] > 0 ) {
		$row['monthly_hours'] = (float) $_POST['monthly_hours'];
	}
	$out = array(
		'found' => true, 'duplicate' => false, 'dry_run' => $dry, 'client_id' => (int) $c->id,
		'fresh_start' => $fresh, 'hours_before' => $before, 'hours_after' => $after,
		'added' => round( $after - $before, 2 ), 'hours_used' => $used,
		'available' => round( max( 0, $after - $used ), 2 ),
		'end_before' => $old_end, 'end_after' => $end,
	);
	if ( $dry ) {
		wp_send_json_success( $out );
	}
	$wpdb->update( $ct, $row, array( 'id' => $c->id ) );
	if ( $ref ) {
		$refs[ $ref ] = current_time( 'mysql' );
		if ( count( $refs ) > 1000 ) {
			$refs = array_slice( $refs, -1000, null, true );
		}
		update_option( 'mwm_portal_topup_refs', $refs, false );
	}
	wp_send_json_success( $out );
}
