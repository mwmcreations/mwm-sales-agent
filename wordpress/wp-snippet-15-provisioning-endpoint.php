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
		'monthly_hours'       => 4,
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
