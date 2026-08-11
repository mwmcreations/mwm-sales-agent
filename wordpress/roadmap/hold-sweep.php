<?php
// Code Snippets plugin — MWM ROADMAP™ · HOLD SWEEP (spec §6.3, §7.6)
// WP Code Snippets ID 40 · ACTIVE · DEV · Aug 11 2026 · v1.0.0
//
// The portal tells a client "we are holding this day for you" and the schema
// stores hold_expires_at. Until this snippet existed, NOTHING ENFORCED IT.
//
// 🔴 A rule that lives only in copy is a rule nobody enforces. The portal made a
// promise about 48 hours and the only thing standing behind it was a timestamp
// nobody read.
//
// 🔴 SILENCE MUST NEVER BE THE THING THAT DECIDES. That is how a client turns up
// to a shoot nobody booked. So this does two things on a schedule:
//   · at 24h unconfirmed  → nudge MWM (spec §7.6). Once per request, never a drip.
//   · at hold expiry      → release the day, and TELL THE CLIENT it was released.
//
// Deliberately separate from the portal snippet: it shares no function names, so
// the two can be updated independently without a redeclare fatal.

if ( ! defined( 'ABSPATH' ) ) { exit; }

define( 'MWM_RM_SWEEP_VERSION', '1.0.0' );

/* ── schedule ─────────────────────────────────────────────────────────── */

add_action( 'init', function () {
	if ( ! wp_next_scheduled( 'mwm_rm_sweep_holds' ) ) {
		wp_schedule_event( time() + 300, 'hourly', 'mwm_rm_sweep_holds' );
	}
} );

// ⚠️ WP-Cron only fires on a page request. mwmcreations.com gets steady traffic,
// so hourly is realistic — but this is a best-effort clock, not a real one. The
// release is therefore written to be SAFE WHEN LATE: it re-checks the expiry at
// run time and never releases anything a human has already confirmed.
add_action( 'mwm_rm_sweep_holds', 'mwm_rm_sweep_holds_run' );

function mwm_rm_sweep_holds_run() {

	global $wpdb;
	$tc = $wpdb->prefix . 'mwm_roadmap_campaigns';
	$tl = $wpdb->prefix . 'mwm_roadmap_clients';

	if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $tc ) ) !== $tc ) { return; }

	$now      = current_time( 'mysql' );
	$released = 0;
	$nudged   = 0;

	$rows = $wpdb->get_results( $wpdb->prepare(
		"SELECT c.*, l.email AS client_email, l.company, l.client_name, l.strategist
		   FROM {$tc} c JOIN {$tl} l ON l.id = c.client_id
		  WHERE c.shoot_state = 'pre_scheduled'
		    AND c.hold_expires_at IS NOT NULL
		  ORDER BY c.hold_expires_at ASC LIMIT %d", 50 ) );

	foreach ( $rows as $r ) {

		$who   = $r->company ? $r->company : $r->client_name;
		$when  = date_i18n( 'l j F', strtotime( $r->shoot_at ) );
		$admin = admin_url( 'admin.php?page=mwm-roadmap-requests' );

		// ── expired: release it ──────────────────────────────────────────
		if ( strtotime( $r->hold_expires_at ) <= strtotime( $now ) ) {

			$ok = $wpdb->update( $tc, array(
				'shoot_at'        => null,
				'shoot_end'       => null,
				'shoot_state'     => 'none',
				'status'          => 'planned',
				'hold_expires_at' => null,
			), array(
				'id'          => (int) $r->id,
				// Re-assert the state in the WHERE clause. If a producer confirmed
				// it in the seconds since the SELECT, this update matches nothing
				// and we do not stamp on their decision.
				'shoot_state' => 'pre_scheduled',
			) );

			if ( ! $ok ) { continue; }
			$released++;
			delete_option( 'mwm_rm_nudged_' . (int) $r->id );

			// 🔴 The client is told. A day that quietly vanishes is worse than a
			// day that was never held — they would arrive expecting a crew.
			wp_mail(
				$r->client_email,
				'The day you asked for has been released',
				"Hi,\n\nWe were holding " . $when . " for " . $r->title . ", but we have not been\n"
				. "able to confirm it in time, so the day has been released and is no longer held.\n\n"
				. "Nothing has been lost — that campaign is still yours and still in your plan.\n"
				. "Pick another day whenever you are ready:\n\n"
				. home_url( '/roadmap-portal/' ) . "\n\n"
				. "If " . $when . " still works for you, ask again and we will get straight to it.\n"
			);

			wp_mail(
				'info@mwmcreations.com',
				'⏳ Hold expired — ' . $who . ' · ' . $when . ' released',
				"A filming request from " . $who . " expired without a decision and has been\n"
				. "released automatically. The client has been told.\n\n"
				. "Campaign: " . $r->title . "\n"
				. "Day:      " . $when . "\n"
				. "Asked:    " . date_i18n( 'j M, g:ia', strtotime( $r->requested_at ) ) . "\n\n"
				. "This is the 48-hour rule doing its job, but a request reaching this point\n"
				. "means nobody looked at it for two days. " . $admin . "\n"
			);
			continue;
		}

		// ── 24 hours in, still nothing: nudge MWM once (spec §7.6) ────────
		$age_hours = ( strtotime( $now ) - strtotime( $r->requested_at ) ) / HOUR_IN_SECONDS;
		$flag      = 'mwm_rm_nudged_' . (int) $r->id;

		if ( $age_hours >= 24 && get_option( $flag ) !== '1' ) {
			// Set the flag FIRST. If the mail call dies, the worst case is one
			// missed nudge — not a nudge every hour until someone acts.
			update_option( $flag, '1', false );
			$nudged++;

			$left = max( 0, round( ( strtotime( $r->hold_expires_at ) - strtotime( $now ) ) / HOUR_IN_SECONDS ) );
			wp_mail(
				'info@mwmcreations.com',
				'⏰ Still unconfirmed — ' . $who . ' · ' . $when,
				$who . " asked for " . $when . " a day ago and nobody has confirmed or declined it.\n\n"
				. "Campaign: " . $r->title . "\n"
				. "Where:    " . ( $r->shoot_kind === 'studio' ? 'Studio' : 'ON LOCATION — ' . $r->shoot_location ) . "\n"
				. "Released in roughly " . $left . " hours if nothing happens.\n\n"
				. $admin . "\n"
			);
		}
	}

	if ( $released || $nudged ) {
		error_log( sprintf( '[MWM ROADMAP sweep] released=%d nudged=%d', $released, $nudged ) );
	}
	update_option( 'mwm_rm_sweep_last', $now . ' released=' . $released . ' nudged=' . $nudged, false );
}
