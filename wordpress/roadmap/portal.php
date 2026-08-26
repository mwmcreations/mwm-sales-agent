<?php
// Code Snippets plugin — MWM ROADMAP™ Portal · LOGIN + READ-ONLY RENDER
// WP Code Snippets ID 51 · ACTIVE · DEV · Aug 26 2026 · v1.5.0
// v1.5.0 — Attention-card text now COMPUTES its figures instead of storing them.
//          A stored number is true on the day it is seeded and wrong afterwards;
//          the cards were still saying "95 days" and "11 studio hours" while the
//          meters on the same page said 80 and 10.5. Two figures disagreeing in
//          front of a client costs trust in ALL of them. Seed a token, not a number.
//          (Same lesson as v1.0.2 and the studio meter — applied to the surface
//          that was missed.)
// v1.4.0 — Confirm now writes the day to the MWM CREATIONS calendar and REPORTS
//          what happened. Before this, Confirm wrote a row and told the client
//          the day was booked; no crew ever saw it and no screen said so.
//
// 🔴 FILENAME RULE CHANGED FOR THESE THREE FILES. wordpress/SNIPPET-INVENTORY.md
// says a mirror is named for its Code Snippets ID. That rule assumed IDs are
// stable. They are not: the Import screen's "Replace any existing snippets"
// option DOES NOT REPLACE — every re-import mints a NEW ID, so this file was
// snippet 27 then 30 inside one afternoon. Renaming the mirror each time
// is how a repo ends up with three stale copies of the same code.
// These three keep a STABLE name; the live ID is recorded on the line above and
// in SNIPPET-INVENTORY.md. Verify it against the snippets list, never assume.
//
// ⚠️ It is 27, not 22. Snippet 22 was the first import; the Import screen's
// "Replace any existing snippets" option did NOT replace it — it created a
// second snippet under a new ID. 22 was deactivated and trashed, 27 is live.
// The filename follows the WP ID, per wordpress/SNIPPET-INVENTORY.md.
// 🔴 Never leave two copies of this file active at once: both declare the same
// functions, and WordPress will fatal on redeclare.
// Spec: docs/ROADMAP_Portal_Spec.md §1 §3 §10 · Strategy: docs/ROADMAP_Strategy.md
//
// Phase 2 of 7. Renders the client's year from the snippet-21 tables. READ ONLY —
// the client cannot write to the database from this build. Approval (§5) and
// pre-scheduling (§6) are later phases and are deliberately absent.
//
// Usage: put [mwm_roadmap_portal] on a page (suggested slug /roadmap-portal/).
//
// ─────────────────────────────────────────────────────────────────────────────
// 🔴 THE FOUR RULES THIS FILE EXISTS TO OBEY. Break one and the program breaks.
//
//   1. NEVER print an edit-day number. Edit days are MWM's cost structure.
//      The client sees a FULLNESS METER and nothing else. (Strategy §3)
//   2. NEVER print an hours figure against a campaign. A campaign is a full
//      production day with no published hour count. (Strategy §1)
//   3. NEVER print a fixed deliverable count as a promise. Deliverables follow
//      from what the campaign was. (Strategy §1)
//   4. NEVER COMPUTE A DELIVERY DATE. One editor is shared across every client,
//      so a computed date is a promise we cannot keep and the client can never
//      see the queue that would explain it. Show STATE. A date appears only when
//      a human has committed one. (Strategy §5.2)
//
// There is no queue position, no other client, and no capacity number anywhere
// in the markup below. That is not an oversight.
// ─────────────────────────────────────────────────────────────────────────────

if ( ! defined( 'ABSPATH' ) ) { exit; }

define( 'MWM_RM_PORTAL_VERSION', '1.0.0' );
define( 'MWM_RM_COOKIE', 'mwm_rm_sess' );
define( 'MWM_RM_SESSION_HOURS', 12 );

/* ===========================================================================
 * SESSION — signed cookie, no server-side row needed
 * The cookie carries client_id|expiry|hmac. The HMAC is over the id, the
 * expiry AND the stored password hash, so changing a client's access code
 * invalidates every outstanding session for free.
 * ======================================================================== */

function mwm_rm_sign( $client_id, $expiry, $pw_hash ) {
	return hash_hmac( 'sha256', $client_id . '|' . $expiry . '|' . $pw_hash, wp_salt( 'auth' ) );
}

function mwm_rm_set_session( $client ) {
	$expiry = time() + ( MWM_RM_SESSION_HOURS * HOUR_IN_SECONDS );
	$val    = $client->id . '|' . $expiry . '|' . mwm_rm_sign( $client->id, $expiry, $client->access_code );
	setcookie( MWM_RM_COOKIE, $val, array(
		'expires'  => $expiry,
		'path'     => '/',
		'secure'   => is_ssl(),
		'httponly' => true,
		'samesite' => 'Lax',
	) );
	$_COOKIE[ MWM_RM_COOKIE ] = $val;
}

function mwm_rm_clear_session() {
	setcookie( MWM_RM_COOKIE, '', array( 'expires' => time() - 3600, 'path' => '/' ) );
	unset( $_COOKIE[ MWM_RM_COOKIE ] );
}

if ( ! function_exists( 'mwm_rm_current_client' ) ) :
function mwm_rm_current_client() {
	if ( empty( $_COOKIE[ MWM_RM_COOKIE ] ) ) { return null; }

	$parts = explode( '|', wp_unslash( $_COOKIE[ MWM_RM_COOKIE ] ) );
	if ( count( $parts ) !== 3 ) { return null; }

	list( $id, $expiry, $sig ) = $parts;
	if ( ! ctype_digit( $id ) || ! ctype_digit( $expiry ) || (int) $expiry < time() ) { return null; }

	global $wpdb;
	$t      = $wpdb->prefix . 'mwm_roadmap_clients';
	$client = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$t} WHERE id = %d", (int) $id ) );

	if ( ! $client || $client->status !== 'active' ) { return null; }
	if ( ! hash_equals( mwm_rm_sign( $client->id, $expiry, $client->access_code ), $sig ) ) { return null; }

	return $client;
}
endif;

/* ===========================================================================
 * RATE LIMITING — same posture as the studio portal
 * ======================================================================== */

function mwm_rm_rate_key( $email ) { return 'mwm_rm_try_' . md5( strtolower( $email ) ); }

function mwm_rm_is_rate_limited( $email ) {
	return (int) get_transient( mwm_rm_rate_key( $email ) ) >= 5;
}

function mwm_rm_record_attempt( $email ) {
	$k = mwm_rm_rate_key( $email );
	set_transient( $k, (int) get_transient( $k ) + 1, 15 * MINUTE_IN_SECONDS );
}

/* ===========================================================================
 * DATA
 * ======================================================================== */

function mwm_rm_campaigns( $client_id ) {
	global $wpdb;
	$t = $wpdb->prefix . 'mwm_roadmap_campaigns';
	return $wpdb->get_results( $wpdb->prepare(
		"SELECT * FROM {$t} WHERE client_id = %d ORDER BY month_no ASC, id ASC", $client_id
	) );
}

function mwm_rm_assets_by_campaign( $campaign_ids ) {
	global $wpdb;
	if ( empty( $campaign_ids ) ) { return array(); }
	$t   = $wpdb->prefix . 'mwm_roadmap_assets';
	$in  = implode( ',', array_map( 'intval', $campaign_ids ) );
	$out = array();
	foreach ( $wpdb->get_results( "SELECT * FROM {$t} WHERE campaign_id IN ({$in}) ORDER BY kind ASC, id ASC" ) as $a ) {
		$out[ (int) $a->campaign_id ][] = $a;
	}
	return $out;
}

function mwm_rm_participants_by_campaign( $campaign_ids ) {
	global $wpdb;
	if ( empty( $campaign_ids ) ) { return array(); }
	$t   = $wpdb->prefix . 'mwm_roadmap_participants';
	$in  = implode( ',', array_map( 'intval', $campaign_ids ) );
	$out = array();
	foreach ( $wpdb->get_results( "SELECT * FROM {$t} WHERE campaign_id IN ({$in}) ORDER BY sort_order ASC, id ASC" ) as $p ) {
		$out[ (int) $p->campaign_id ][] = $p;
	}
	return $out;
}

function mwm_rm_open_actions( $client_id ) {
	global $wpdb;
	$t = $wpdb->prefix . 'mwm_roadmap_actions';
	return $wpdb->get_results( $wpdb->prepare(
		"SELECT * FROM {$t} WHERE client_id = %d AND resolved = 0 ORDER BY due_date IS NULL, due_date ASC, id ASC", $client_id
	) );
}

function mwm_rm_captures( $client_id ) {
	global $wpdb;
	$t = $wpdb->prefix . 'mwm_roadmap_captures';
	return $wpdb->get_results( $wpdb->prepare(
		"SELECT * FROM {$t} WHERE client_id = %d ORDER BY id DESC", $client_id
	) );
}

/* ===========================================================================
 * STUDIO HOURS — read, never merge
 * The studio portal and this one are SEPARATE PRODUCTS with separate logins
 * (Michael, Aug 11). But a Gold plan includes studio hours, so this page has to
 * say how many are left, and the only honest source is the studio ledger.
 *
 * 🔴 Do not hardcode this number. It was seeded as 0 once and was wrong within
 * the hour — Z Brothers had already used one. A figure the client can check
 * against their own memory must be computed, not stored.
 *
 * Mirrors mwm-studio-booking.php::hours_used_in_contract() exactly, including
 * counting 'cancelled_late' — a late cancellation burns the hour there, so it
 * has to burn it here too or the two products will disagree in front of a client.
 * ======================================================================== */

add_filter( 'mwm_rm_studio_hours_used', function ( $default, $client ) {
	global $wpdb;

	if ( empty( $client->studio_client_id ) ) { return $default; }

	$bookings = $wpdb->prefix . 'mwm_studio_bookings';
	$clients  = $wpdb->prefix . 'mwm_studio_clients';
	if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $bookings ) ) !== $bookings ) {
		return $default;
	}

	// 🔴 USE THE STUDIO CONTRACT'S OWN WINDOW, NOT THE ROADMAP ONE.
	// The first version scoped this to the roadmap contract year, which is wider.
	// It swept up bookings from an EARLIER studio contract and reported 8 hours
	// used where the studio product reports 1 — two screens disagreeing about the
	// same client, which is the one thing this filter exists to prevent.
	// Mirroring the studio product's own window means they cannot drift.
	$sc = $wpdb->get_row( $wpdb->prepare(
		"SELECT contract_start_date, contract_end_date FROM {$clients} WHERE id = %d",
		(int) $client->studio_client_id
	) );

	if ( $sc && ! empty( $sc->contract_start_date ) && ! empty( $sc->contract_end_date ) ) {
		$used = $wpdb->get_var( $wpdb->prepare(
			"SELECT COALESCE(SUM(duration_hours),0) FROM {$bookings}
			 WHERE client_id = %d
			   AND status IN ('confirmed','completed','cancelled_late')
			   AND booking_date >= %s AND booking_date <= %s",
			(int) $client->studio_client_id, $sc->contract_start_date, $sc->contract_end_date
		) );
	} else {
		// No dates on the studio row — same fallback the studio product uses.
		$used = $wpdb->get_var( $wpdb->prepare(
			"SELECT COALESCE(SUM(duration_hours),0) FROM {$bookings}
			 WHERE client_id = %d AND status IN ('confirmed','completed','cancelled_late')",
			(int) $client->studio_client_id
		) );
	}

	return (float) $used;
}, 10, 2 );

/* ===========================================================================
 * PRESENTATION HELPERS
 * ======================================================================== */

// 🔴 The client-facing ladder. NOT the internal one. There is no "in edit
// position 3 of 7" here and there never will be.
function mwm_rm_status_label( $status ) {
	$map = array(
		'planned'   => 'Planned',
		'scheduled' => 'Scheduled',
		'filmed'    => 'Filmed',
		'editing'   => 'Editing now',
		'delivered' => 'Delivered',
	);
	return isset( $map[ $status ] ) ? $map[ $status ] : ucfirst( $status );
}

function mwm_rm_status_step( $status ) {
	$map = array( 'planned' => 1, 'scheduled' => 2, 'filmed' => 3, 'editing' => 4, 'delivered' => 5 );
	return isset( $map[ $status ] ) ? $map[ $status ] : 1;
}

/**
 * Render a figure the way the meters do: 4, not 4.0 — but 10.5 stays 10.5.
 */
function mwm_rm_num( $n ) {
	return rtrim( rtrim( number_format( (float) $n, 1 ), '0' ), '.' );
}

/**
 * Substitute {tokens} in client-facing card text.
 *
 * A card may state a figure that a meter on the same page also states. Storing
 * that figure freezes it at seed time; the meter keeps counting. Store the
 * token and let both come from one calculation.
 */
function mwm_rm_fill( $text, $tokens ) {
	if ( ! is_string( $text ) || $text === '' || strpos( $text, '{' ) === false ) {
		return $text;
	}
	return strtr( $text, $tokens );
}

function mwm_rm_fmt_date( $dt, $fmt = 'D j M Y' ) {
	if ( empty( $dt ) || $dt === '0000-00-00' || $dt === '0000-00-00 00:00:00' ) { return ''; }
	return date_i18n( $fmt, strtotime( $dt ) );
}

function mwm_rm_days_until( $date ) {
	if ( empty( $date ) ) { return null; }
	$d = ( strtotime( $date ) - strtotime( current_time( 'Y-m-d' ) ) ) / DAY_IN_SECONDS;
	return (int) round( $d );
}

// The four confirmations (Strategy §8). A gap is SHOWN, never hidden — a gap the
// portal states out loud is a gap that gets filled before the shoot day.
function mwm_rm_confirmations( $campaign, $participants, $assets ) {
	$out = array();

	$out[] = array(
		'label' => 'Date',
		'done'  => ( $campaign->shoot_state === 'confirmed' && ! empty( $campaign->shoot_at ) ),
		'value' => ! empty( $campaign->shoot_at )
			? mwm_rm_fmt_date( $campaign->shoot_at, 'D j M · g:ia' )
			: 'Not yet chosen',
	);

	$out[] = array(
		'label' => 'Location',
		'done'  => ( $campaign->shoot_location !== '' ),
		'value' => $campaign->shoot_location !== '' ? $campaign->shoot_location : 'We need an address from you',
	);

	// A script is an ASSET, so it runs the same approval machine as a film.
	$script = null;
	foreach ( $assets as $a ) {
		if ( $a->kind === 'script' ) { $script = $a; break; }
	}
	$out[] = array(
		'label' => 'Script',
		'done'  => ( $script && $script->review_state === 'approved' ),
		'value' => ! $script
			? 'Not written yet'
			: ( $script->review_state === 'approved'
				? 'Approved by you' . ( $script->reviewed_at ? ' · ' . mwm_rm_fmt_date( $script->reviewed_at, 'j M' ) : '' )
				: ( $script->review_state === 'fix' ? 'You asked for changes' : 'Waiting for your approval' ) ),
	);

	$people_done = ! empty( $participants );
	$pending     = 0;
	$gaps        = 0;
	foreach ( $participants as $p ) {
		if ( (int) $p->placeholder === 1 ) { $gaps++; $people_done = false; }
		elseif ( $p->confirm_state !== 'confirmed' ) { $pending++; $people_done = false; }
	}
	if ( empty( $participants ) ) {
		$pv = 'Nobody added yet';
	} elseif ( $people_done ) {
		$pv = count( $participants ) . ' confirmed';
	} else {
		$bits = array();
		if ( $gaps )    { $bits[] = $gaps . ' still to be chosen'; }
		if ( $pending ) { $bits[] = $pending . ' awaiting reply'; }
		$pv = implode( ' · ', $bits );
	}
	$out[] = array( 'label' => 'People', 'done' => $people_done, 'value' => $pv );

	return $out;
}

/* ===========================================================================
 * PRE-SCHEDULING — the client picks a day, MWM confirms  (Spec §6)
 *
 * 🔴 A PRE-SCHEDULE IS NOT A BOOKING. Picking a day files a request and holds
 * the slot; the shoot is not real until a producer confirms it. That single
 * distinction is what makes it safe to hand a client a calendar at all, and
 * every string below is written so the client can never mistake one for the
 * other.
 *
 * 🔴 THE NOTICE RULE HAS EXACTLY ONE IMPLEMENTATION: mwm_rm_notice_days().
 * The browser uses it (via the min= attribute this file emits) and the submit
 * handler re-checks it. When two places must agree on a rule, one function has
 * to produce both — otherwise the day comes when they disagree and the crew
 * eats it.
 *
 * 🔴 Days inside the notice window are UNPICKABLE, not warned about. A rule you
 * can click through is a rule you will be asked to break.
 * ======================================================================== */

// Studio 48 hours · on location 7 days. Michael's rule, spec §6.2.
function mwm_rm_notice_days( $kind ) {
	return ( $kind === 'studio' ) ? 2 : 7;
}

function mwm_rm_is_closed_day( $ymd ) {
	// Sundays closed by default (spec §6.3).
	return ( (int) date( 'w', strtotime( $ymd ) ) === 0 );
}

/**
 * The earliest day that BOTH clears the notice window and is open.
 * Named separately from the raw cutoff on purpose: the raw cutoff can land on a
 * Sunday, and telling a client "from the 14th" when the 14th is closed is the
 * kind of small lie that costs a phone call.
 */
function mwm_rm_earliest_open( $kind ) {
	$d = strtotime( current_time( 'Y-m-d' ) . ' +' . mwm_rm_notice_days( $kind ) . ' days' );
	for ( $i = 0; $i < 14; $i++ ) {
		$ymd = date( 'Y-m-d', $d );
		if ( ! mwm_rm_is_closed_day( $ymd ) ) { return $ymd; }
		$d = strtotime( '+1 day', $d );
	}
	return date( 'Y-m-d', $d );
}

/** Server-side gate. Returns '' when the date is acceptable, else the reason. */
function mwm_rm_reject_reason( $ymd, $kind ) {
	if ( ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', $ymd ) || ! strtotime( $ymd ) ) {
		return 'That date did not look like a date.';
	}
	if ( mwm_rm_is_closed_day( $ymd ) ) {
		return 'We are closed on Sundays.';
	}
	if ( strtotime( $ymd ) < strtotime( mwm_rm_earliest_open( $kind ) ) ) {
		return ( $kind === 'studio' )
			? 'Studio days need 48 hours of notice. The earliest we can take is ' . mwm_rm_fmt_date( mwm_rm_earliest_open( 'studio' ), 'l j F' ) . '.'
			: 'Filming on location needs 7 days of notice. The earliest we can take is ' . mwm_rm_fmt_date( mwm_rm_earliest_open( 'location' ), 'l j F' ) . '.';
	}
	return '';
}

function mwm_rm_windows() {
	return array(
		'morning'   => array( 'label' => 'Morning · 9am – 12pm',   'start' => '09:00', 'end' => '12:00' ),
		'afternoon' => array( 'label' => 'Afternoon · 1pm – 4pm',  'start' => '13:00', 'end' => '16:00' ),
		'fullday'   => array( 'label' => 'Full day · 9am – 5pm',   'start' => '09:00', 'end' => '17:00' ),
	);
}

/**
 * Handle a request. Returns array( 'error' => string ) or array( 'ok' => campaign row ).
 * Every check here is duplicated in the browser for convenience only — the
 * browser is never trusted on a rule that costs a crew day.
 */
function mwm_rm_handle_request( $client ) {

	global $wpdb;
	$t = $wpdb->prefix . 'mwm_roadmap_campaigns';

	$campaign_id = isset( $_POST['campaign_id'] ) ? (int) $_POST['campaign_id'] : 0;
	$kind        = ( isset( $_POST['shoot_kind'] ) && $_POST['shoot_kind'] === 'studio' ) ? 'studio' : 'location';
	$date        = isset( $_POST['shoot_date'] ) ? sanitize_text_field( wp_unslash( $_POST['shoot_date'] ) ) : '';
	$window      = isset( $_POST['window'] ) ? sanitize_text_field( wp_unslash( $_POST['window'] ) ) : '';
	$address     = isset( $_POST['address'] ) ? sanitize_text_field( wp_unslash( $_POST['address'] ) ) : '';
	$notes       = isset( $_POST['notes'] ) ? sanitize_textarea_field( wp_unslash( $_POST['notes'] ) ) : '';

	$windows = mwm_rm_windows();
	if ( ! isset( $windows[ $window ] ) ) { return array( 'error' => 'Please choose a time of day.' ); }

	// The campaign must be THIS client's, and must not already be spent or held.
	$campaign = $wpdb->get_row( $wpdb->prepare(
		"SELECT * FROM {$t} WHERE id = %d AND client_id = %d", $campaign_id, $client->id
	) );
	if ( ! $campaign ) { return array( 'error' => 'Please choose which campaign this is for.' ); }
	if ( $campaign->status !== 'planned' ) {
		return array( 'error' => 'That campaign has already been filmed.' );
	}
	if ( in_array( $campaign->shoot_state, array( 'pre_scheduled', 'confirmed' ), true ) ) {
		return array( 'error' => 'That campaign already has a day held. Speak to your strategist to move it.' );
	}

	$why = mwm_rm_reject_reason( $date, $kind );
	if ( $why !== '' ) { return array( 'error' => $why ); }

	// 🔴 A full street address is mandatory on location (Strategy §8). A crew
	// cannot be sent to "the new house".
	if ( $kind === 'location' && strlen( trim( $address ) ) < 8 ) {
		return array( 'error' => 'We need the full street address for an on-location day.' );
	}

	$start = $date . ' ' . $windows[ $window ]['start'] . ':00';
	$end   = $date . ' ' . $windows[ $window ]['end'] . ':00';

	$ok = $wpdb->update( $t, array(
		'shoot_at'        => $start,
		'shoot_end'       => $end,
		'shoot_kind'      => $kind,
		'shoot_location'  => ( $kind === 'studio' ) ? 'MWM Creations & Studios' : $address,
		'shoot_state'     => 'pre_scheduled',
		'status'          => 'scheduled',
		'requested_by'    => $client->email,
		'requested_at'    => current_time( 'mysql' ),
		// Spec §6.3 — an unconfirmed hold must not sit on a day forever.
		'hold_expires_at' => date( 'Y-m-d H:i:s', strtotime( current_time( 'mysql' ) . ' +48 hours' ) ),
	), array( 'id' => (int) $campaign->id ) );

	if ( $ok === false ) { return array( 'error' => 'Something went wrong saving that. Please try again.' ); }

	if ( $notes !== '' ) {
		$wpdb->insert( $wpdb->prefix . 'mwm_roadmap_actions', array(
			'client_id'   => $client->id,
			'campaign_id' => (int) $campaign->id,
			'title'       => 'Notes for ' . $campaign->title,
			'detail'      => $notes,
			'resolved'    => 0,
		) );
	}

	mwm_rm_notify_request( $client, $campaign, $date, $windows[ $window ]['label'], $kind, $address, $notes );

	return array( 'ok' => $campaign, 'date' => $date, 'window' => $windows[ $window ]['label'] );
}

/**
 * 🔴 A pre-schedule is not an FYI, it is a task with a clock on it (spec §7.2).
 * An on-location request carries 7 days of runway; if this sits unread for three
 * of them, half the notice Michael just set is gone before anyone looks.
 * So the subject line carries the decision inputs, not just a notification.
 */
function mwm_rm_notify_request( $client, $campaign, $date, $window_label, $kind, $address, $notes ) {

	$where = ( $kind === 'studio' ) ? 'STUDIO' : 'ON LOCATION';
	$subj  = sprintf(
		'🎬 Pre-scheduled — %s · %s, %s · %s',
		$client->company ? $client->company : $client->client_name,
		mwm_rm_fmt_date( $date, 'D j M' ),
		$window_label,
		$where
	);

	$body  = "A ROADMAP client has requested a filming day. NOTHING IS BOOKED until you confirm it.\n\n";
	$body .= "Client:    " . ( $client->company ? $client->company : $client->client_name ) . "\n";
	$body .= "Requested: " . $client->email . "\n";
	$body .= "Campaign:  " . (int) $campaign->month_no . " — " . $campaign->title . "\n";
	$body .= "Date:      " . mwm_rm_fmt_date( $date, 'l j F Y' ) . "\n";
	$body .= "Time:      " . $window_label . "\n";
	$body .= "Type:      " . $where . "\n";
	if ( $kind === 'location' ) { $body .= "Address:   " . $address . "\n"; }
	if ( $notes !== '' )        { $body .= "\nNotes from the client:\n" . $notes . "\n"; }
	$body .= "\nConfirm or decline here:\n" . admin_url( 'admin.php?page=mwm-roadmap-requests' ) . "\n";
	$body .= "\nThe hold expires in 48 hours. If nobody acts, the day is released and the\n";
	$body .= "client is told — silence must never be the thing that decides.\n";

	wp_mail( 'info@mwmcreations.com', $subj, $body );
}

/* ===========================================================================
 * THE CALENDAR  (v1.4.0)
 *
 * 🔴 A CONFIRMED DAY THAT IS NOT ON A CALENDAR IS NOT CONFIRMED.
 *
 * Until this existed, clicking Confirm wrote 'confirmed' to a row, emailed the
 * client, and stopped. No crew ever saw the day. The studio was free to be
 * booked over it. On Aug 11 that happened for real and nothing on any screen
 * said so — which is the part that makes it dangerous rather than merely
 * missing: the producer walks away believing the day is real.
 *
 * So this pushes to the machine and — unlike the studio path, which fast-ACKs
 * because a paying client is waiting on the HTTP response — it WAITS for the
 * verdict and hands it back. The producer is already looking at the screen.
 * Two seconds buys an honest answer.
 * ======================================================================== */

function mwm_rm_shoot_webhook_url() {
	return get_option( 'mwm_rm_webhook_url',
		'https://mwm-sales-agent-production.up.railway.app/webhook/roadmap-shoot' );
}

/**
 * Push a shoot event to the machine. Returns array( ok, state, note ).
 *
 * 'note' is written for the producer standing in wp-admin, not for a log. It
 * must always be safe to print, and it must never say something happened when
 * it didn't.
 */
function mwm_rm_push_shoot( $event, $row, $client ) {

	$secret = get_option( 'mwm_portal_provision_secret' );
	if ( ! $secret ) {
		return array( 'ok' => false, 'state' => 'unconfigured',
			'note' => 'no calendar event was created — the portal secret is not set on this site' );
	}

	$payload = array(
		'event'          => $event,
		'campaign_id'    => (int) $row->id,
		'campaign_no'    => (int) $row->month_no,
		'campaign_title' => $row->title,
		'client_name'    => $client ? $client->client_name : '',
		'client_email'   => $client ? $client->email : '',
		'date'           => $row->shoot_at ? substr( $row->shoot_at, 0, 10 ) : '',
		'start_time'     => $row->shoot_at ? substr( $row->shoot_at, 11, 5 ) : '',
		'end_time'       => $row->shoot_end ? substr( $row->shoot_end, 11, 5 ) : '',
		'kind'           => $row->shoot_kind,
		'location'       => $row->shoot_location,
		'confirmed_by'   => wp_get_current_user()->user_email,
	);

	$res = wp_remote_post( mwm_rm_shoot_webhook_url(), array(
		'timeout' => 20,   // it writes to Google inline; a short timeout would lie
		'headers' => array(
			'Content-Type'         => 'application/json',
			'X-MWM-Portal-Secret'  => $secret,
		),
		'body'    => wp_json_encode( $payload ),
	) );

	if ( is_wp_error( $res ) ) {
		return array( 'ok' => false, 'state' => 'unreachable',
			'note' => 'no calendar event was created — could not reach the scheduler ('
				. $res->get_error_message() . ')' );
	}

	$code = (int) wp_remote_retrieve_response_code( $res );
	$data = json_decode( wp_remote_retrieve_body( $res ), true );
	$state = is_array( $data ) && isset( $data['state'] ) ? $data['state'] : '';

	if ( $code !== 200 || ! is_array( $data ) || empty( $data['ok'] ) ) {
		$why = is_array( $data ) && ! empty( $data['error'] ) ? $data['error'] : ( 'HTTP ' . $code );
		return array( 'ok' => false, 'state' => $state ? $state : 'failed',
			'note' => 'NO CALENDAR EVENT WAS CREATED — ' . $why );
	}

	if ( $state === 'degraded' ) {
		return array( 'ok' => true, 'state' => $state,
			'note' => 'the day is on the calendar, but the client could not be added as a guest, '
				. 'so no calendar invitation was sent to them' );
	}
	if ( $state === 'removed' ) {
		return array( 'ok' => true, 'state' => $state, 'note' => 'the calendar event was removed' );
	}
	if ( $state === 'nothing_to_remove' || $state === 'already_gone' ) {
		return array( 'ok' => true, 'state' => $state, 'note' => 'there was no calendar event to remove' );
	}
	return array( 'ok' => true, 'state' => 'ok', 'note' => 'it is on the calendar' );
}

/* ===========================================================================
 * MWM SIDE — confirm or decline
 * Without this the portal is a request box that goes nowhere, which is worse
 * than no request box at all.
 * ======================================================================== */

add_action( 'admin_menu', function () {
	add_menu_page(
		'ROADMAP requests', 'ROADMAP requests', 'manage_options',
		'mwm-roadmap-requests', 'mwm_rm_requests_screen', 'dashicons-video-alt2', 26
	);
} );

function mwm_rm_requests_screen() {

	if ( ! current_user_can( 'manage_options' ) ) { return; }

	global $wpdb;
	$tc = $wpdb->prefix . 'mwm_roadmap_campaigns';
	$tl = $wpdb->prefix . 'mwm_roadmap_clients';
	$notice = '';
	$notice_type = 'info';

	if ( isset( $_POST['rm_action'] ) && check_admin_referer( 'mwm_rm_decide' ) ) {
		$id     = (int) $_POST['campaign_id'];
		$reason = isset( $_POST['reason'] ) ? sanitize_text_field( wp_unslash( $_POST['reason'] ) ) : '';
		$row    = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$tc} WHERE id = %d", $id ) );

		if ( $row && $_POST['rm_action'] === 'confirm' ) {
			$wpdb->update( $tc, array(
				'shoot_state'     => 'confirmed',
				'confirmed_by'    => wp_get_current_user()->user_email,
				'confirmed_at'    => current_time( 'mysql' ),
				'hold_expires_at' => null,
			), array( 'id' => $id ) );

			// 🔴 The row says confirmed. Whether a CREW will ever see it is a
			// separate question, and it is the one that matters. Ask it here and
			// say the answer out loud — the DB write is deliberately NOT rolled
			// back on failure, because the client has already been promised the
			// day and a producer can add a calendar entry by hand in ten seconds.
			// What a producer cannot do is find out about a missing one.
			$cl  = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$tl} WHERE id = %d", (int) $row->client_id ) );
			$row = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$tc} WHERE id = %d", $id ) );
			$cal = mwm_rm_push_shoot( 'shoot_confirmed', $row, $cl );

			if ( $cal['ok'] ) {
				$notice = 'Confirmed — ' . $cal['note'] . '. The client now sees it as confirmed on their portal.';
				$notice_type = ( $cal['state'] === 'degraded' ) ? 'warning' : 'success';
			} else {
				$notice = 'CONFIRMED ON THE PORTAL, BUT ' . strtoupper( $cal['note'] ) . '. '
					. 'The client has been told the day is confirmed and nothing is holding it on '
					. 'the calendar — put it there by hand now: '
					. mwm_rm_fmt_date( $row->shoot_at, 'l j F' ) . ', '
					. substr( $row->shoot_at, 11, 5 ) . '–' . substr( (string) $row->shoot_end, 11, 5 ) . ', '
					. ( $row->shoot_location ? $row->shoot_location : 'the studio' ) . '.';
				$notice_type = 'error';
			}

		} elseif ( $row && $_POST['rm_action'] === 'release' ) {
			// 🔴 For a test booking, a duplicate, or anything the client never
			// actually asked for. Same reset as a decline, but NO EMAIL — telling
			// someone you cannot do a day they never requested is worse than
			// silence. Without this, the only way to clear a row was to email
			// the client about it.
			$wpdb->update( $tc, array(
				'shoot_at'        => null,
				'shoot_end'       => null,
				'shoot_state'     => 'none',
				'status'          => 'planned',
				'hold_expires_at' => null,
			), array( 'id' => $id ) );
			delete_option( 'mwm_rm_nudged_' . $id );
			// If it had already been confirmed, an event exists. Freeing the day in
			// the portal while leaving it blocked on the calendar is the same defect
			// in the other direction.
			$cl  = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$tl} WHERE id = %d", (int) $row->client_id ) );
			$cal = mwm_rm_push_shoot( 'shoot_cancelled', $row, $cl );
			$notice = 'Released. The day is free again and the client was NOT emailed. '
				. ucfirst( $cal['note'] ) . '.';
			$notice_type = $cal['ok'] ? 'success' : 'error';

		} elseif ( $row && $_POST['rm_action'] === 'decline' ) {
			// 🔴 A decline REQUIRES a reason and it goes to the client verbatim.
			// "No" with no reason is the thing that costs a round trip.
			if ( $reason === '' ) {
				// 🔴 A REFUSED ACTION MUST NOT LOOK LIKE A COMPLETED ONE.
				// The first version showed a quiet blue notice and left the row
				// looking identical, so it was possible to click Decline, read
				// nothing, and walk away believing the request was gone. It was not.
				// Name the object, say plainly that nothing happened.
				$notice = 'NOTHING WAS DECLINED. ' . ( $row ? ( $row->title . ' for ' ) : '' )
					. 'this request still needs a reason — the reason is emailed to the client '
					. 'word for word, so it cannot be blank. The day is still held.';
				$notice_type = 'error';
			} else {
				$wpdb->update( $tc, array(
					'shoot_at'        => null,
					'shoot_end'       => null,
					'shoot_state'     => 'none',
					'status'          => 'planned',
					'hold_expires_at' => null,
				), array( 'id' => $id ) );
				$cl = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$tl} WHERE id = %d", (int) $row->client_id ) );
				if ( $cl ) {
					wp_mail(
						$cl->email,
						'About the day you asked for',
						"Hi,\n\nWe can't do " . mwm_rm_fmt_date( $row->shoot_at, 'l j F' ) . " for "
						. $row->title . ". Here's why:\n\n" . $reason
						. "\n\nThe day is back in your portal — pick another whenever you're ready.\n\n"
						. home_url( '/roadmap-portal/' ) . "\n"
					);
				}
				$cal = mwm_rm_push_shoot( 'shoot_cancelled', $row, $cl );
				$notice = 'Declined, and the client has been told why. ' . ucfirst( $cal['note'] ) . '.';
				$notice_type = $cal['ok'] ? 'success' : 'error';
			}
		}
	}

	$rows = $wpdb->get_results(
		"SELECT c.*, l.company, l.client_name, l.email
		   FROM {$tc} c JOIN {$tl} l ON l.id = c.client_id
		  WHERE c.shoot_state = 'pre_scheduled'
		  ORDER BY c.shoot_at ASC"
	);
	?>
	<div class="wrap">
		<h1>ROADMAP filming requests</h1>
		<?php if ( $notice ) : ?>
			<div class="notice notice-<?php echo esc_attr( $notice_type ); ?>"><p><strong><?php echo esc_html( $notice ); ?></strong></p></div>
		<?php endif; ?>

		<?php if ( empty( $rows ) ) : ?>
			<p>No requests waiting. When a client picks a day it appears here.</p>
		<?php else : ?>
			<p>These days are <strong>held, not booked</strong>. The client has been told the same thing.</p>
			<table class="widefat striped">
				<thead><tr><th>Client</th><th>Campaign</th><th>Day</th><th>Where</th><th>Asked</th><th style="width:34%">Decide</th></tr></thead>
				<tbody>
				<?php foreach ( $rows as $r ) : ?>
					<tr>
						<td><strong><?php echo esc_html( $r->company ?: $r->client_name ); ?></strong><br>
							<span class="description"><?php echo esc_html( $r->email ); ?></span></td>
						<td>Campaign <?php echo (int) $r->month_no; ?><br>
							<span class="description"><?php echo esc_html( $r->title ); ?></span></td>
						<td><?php echo esc_html( mwm_rm_fmt_date( $r->shoot_at, 'D j M Y' ) ); ?><br>
							<span class="description"><?php echo esc_html( mwm_rm_fmt_date( $r->shoot_at, 'g:ia' ) ); ?>–<?php echo esc_html( mwm_rm_fmt_date( $r->shoot_end, 'g:ia' ) ); ?></span></td>
						<td><?php echo $r->shoot_kind === 'studio' ? 'Studio' : '<strong>On location</strong>'; ?><br>
							<span class="description"><?php echo esc_html( $r->shoot_location ); ?></span></td>
						<td><span class="description"><?php echo esc_html( mwm_rm_fmt_date( $r->requested_at, 'j M, g:ia' ) ); ?><br>
							hold ends <?php echo esc_html( mwm_rm_fmt_date( $r->hold_expires_at, 'j M g:ia' ) ); ?></span></td>
						<td>
							<form method="post" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
								<?php wp_nonce_field( 'mwm_rm_decide' ); ?>
								<input type="hidden" name="campaign_id" value="<?php echo (int) $r->id; ?>">
								<button class="button button-primary" name="rm_action" value="confirm">Confirm</button>
								<input type="text" name="reason" placeholder="Reason, sent to the client" style="flex:1;min-width:150px">
								<button class="button" name="rm_action" value="decline"
									onclick="var r=this.form.reason; if(!r.value.trim()){ r.focus(); r.style.outline='2px solid #d03b3b'; alert('A decline needs a reason. It is emailed to the client word for word.'); return false; }">Decline</button>
								<button class="button button-link-delete" name="rm_action" value="release"
									title="Clear this request without emailing the client — for a test or something they never asked for."
									onclick="return confirm('Release this day without emailing the client?');">Release quietly</button>
							</form>
						</td>
					</tr>
				<?php endforeach; ?>
				</tbody>
			</table>
		<?php endif; ?>
	</div>
	<?php
}

/* ===========================================================================
 * SHORTCODE
 * ======================================================================== */

// The portal is a full application surface, not an article. Most themes cap a
// page's content column somewhere around 960px, which squeezes the four stat
// tiles and the booking table. Tag the body on any page carrying the shortcode
// so the CSS below can widen just that page — no theme edit, no page template
// to remember to set, and nothing changes on any other page.
add_filter( 'body_class', function ( $classes ) {
	if ( is_singular() ) {
		$post = get_post();
		if ( $post && has_shortcode( (string) $post->post_content, 'mwm_roadmap_portal' ) ) {
			$classes[] = 'mwm-roadmap-page';
		}
	}
	return $classes;
} );

add_shortcode( 'mwm_roadmap_portal', 'mwm_rm_render' );

function mwm_rm_render( $atts = array() ) {

	// Never let a page cache serve one client's portal to another.
	if ( ! defined( 'DONOTCACHEPAGE' ) ) { define( 'DONOTCACHEPAGE', true ); }
	nocache_headers();

	$error = '';

	// ── logout ──────────────────────────────────────────────────────────
	if ( isset( $_GET['mwm_rm_logout'] ) ) {
		mwm_rm_clear_session();
		wp_safe_redirect( remove_query_arg( 'mwm_rm_logout' ) );
		exit;
	}

	// ── login ───────────────────────────────────────────────────────────
	if ( isset( $_POST['mwm_rm_login'] ) ) {
		if ( ! isset( $_POST['mwm_rm_nonce'] ) || ! wp_verify_nonce( wp_unslash( $_POST['mwm_rm_nonce'] ), 'mwm_rm_login' ) ) {
			$error = 'Your session expired. Please try again.';
		} else {
			$email = isset( $_POST['email'] ) ? sanitize_email( wp_unslash( $_POST['email'] ) ) : '';
			$code  = isset( $_POST['access_code'] ) ? strtoupper( trim( sanitize_text_field( wp_unslash( $_POST['access_code'] ) ) ) ) : '';

			if ( ! is_email( $email ) || $code === '' ) {
				$error = 'Please enter your email and your 6-character access code.';
			} elseif ( mwm_rm_is_rate_limited( $email ) ) {
				$error = 'Too many attempts. Please try again in 15 minutes.';
			} else {
				global $wpdb;
				$t      = $wpdb->prefix . 'mwm_roadmap_clients';
				$client = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$t} WHERE email = %s", $email ) );

				if ( ! $client || $client->status !== 'active' || ! wp_check_password( $code, $client->access_code ) ) {
					mwm_rm_record_attempt( $email );
					// Deliberately identical for every failure mode — never reveal
					// whether an address is a client.
					$error = 'That email and access code do not match.';
				} else {
					delete_transient( mwm_rm_rate_key( $email ) );
					mwm_rm_set_session( $client );
					wp_safe_redirect( remove_query_arg( array( 'mwm_rm_logout' ) ) );
					exit;
				}
			}
		}
	}

	$client = mwm_rm_current_client();

	// ── a filming-day request (the first place a client writes to the DB) ──
	$req_error = '';
	$req_ok    = null;
	if ( $client && isset( $_POST['mwm_rm_request'] ) ) {
		if ( ! isset( $_POST['mwm_rm_rnonce'] ) || ! wp_verify_nonce( wp_unslash( $_POST['mwm_rm_rnonce'] ), 'mwm_rm_request' ) ) {
			$req_error = 'Your session expired. Please try again.';
		} else {
			$res = mwm_rm_handle_request( $client );
			if ( isset( $res['error'] ) ) { $req_error = $res['error']; }
			else { $req_ok = $res; }
		}
	}

	ob_start();
	echo mwm_rm_styles();
	if ( ! $client ) {
		mwm_rm_login_screen( $error );
	} else {
		mwm_rm_portal_screen( $client, $req_error, $req_ok );
	}
	return ob_get_clean();
}

/* ===========================================================================
 * LOGIN SCREEN
 * ======================================================================== */

function mwm_rm_login_screen( $error = '' ) { ?>
<div class="mwmrm" data-theme="light">
  <div class="rm-login">
    <div class="rm-lbrand">MWM ROADMAP<sup>™</sup></div>
    <h1 class="rm-ltitle">Your year, in one place.</h1>
    <p class="rm-lsub">Sign in with the email on your contract and the 6-character access code we sent you.</p>

    <?php if ( $error ) : ?>
      <div class="rm-err" role="alert"><?php echo esc_html( $error ); ?></div>
    <?php endif; ?>

    <form method="post" class="rm-lform" autocomplete="on">
      <?php wp_nonce_field( 'mwm_rm_login', 'mwm_rm_nonce' ); ?>
      <label class="rm-lab" for="rm-email">Email</label>
      <input class="rm-in" type="email" name="email" id="rm-email" required autocomplete="email"
             value="<?php echo isset( $_POST['email'] ) ? esc_attr( sanitize_email( wp_unslash( $_POST['email'] ) ) ) : ''; ?>">

      <label class="rm-lab" for="rm-code">Access code</label>
      <input class="rm-in rm-code" type="text" name="access_code" id="rm-code" required
             maxlength="6" inputmode="text" spellcheck="false" autocapitalize="characters"
             placeholder="ABC123" autocomplete="one-time-code">

      <button class="rm-btn" type="submit" name="mwm_rm_login" value="1">Sign in</button>
    </form>

    <p class="rm-lfoot">Lost your code? Access codes cannot be recovered — email
      <a href="mailto:info@mwmcreations.com">info@mwmcreations.com</a> and we will issue a new one.</p>
  </div>
</div>
<?php }

/* ===========================================================================
 * PORTAL
 * ======================================================================== */

function mwm_rm_portal_screen( $client, $req_error = '', $req_ok = null ) {

	$campaigns    = mwm_rm_campaigns( $client->id );
	$ids          = wp_list_pluck( $campaigns, 'id' );
	$assets_by    = mwm_rm_assets_by_campaign( $ids );
	$people_by    = mwm_rm_participants_by_campaign( $ids );
	$actions      = mwm_rm_open_actions( $client->id );
	$captures     = mwm_rm_captures( $client->id );

	// ── counts. Campaign is spent ON THE SHOOT DAY (Strategy §10.5), so
	// anything filmed or later has been spent.
	$spent = 0; $delivered = 0; $awaiting = 0; $film_count = 0;
	$next  = null;
	$now   = current_time( 'timestamp' );

	foreach ( $campaigns as $c ) {
		if ( in_array( $c->status, array( 'filmed', 'editing', 'delivered' ), true ) ) { $spent++; }
		if ( $c->status === 'delivered' ) { $delivered++; }
		if ( ! empty( $c->shoot_at ) && strtotime( $c->shoot_at ) >= $now
		     && in_array( $c->shoot_state, array( 'confirmed', 'pre_scheduled', 'proposed' ), true ) ) {
			if ( ! $next || strtotime( $c->shoot_at ) < strtotime( $next->shoot_at ) ) { $next = $c; }
		}
		foreach ( ( isset( $assets_by[ (int) $c->id ] ) ? $assets_by[ (int) $c->id ] : array() ) as $a ) {
			// 'other' is the convenience folder link, not a film. Counting it would inflate
			// a number the client can check against their own Drive.
			if ( ! in_array( $a->kind, array( 'script', 'other' ), true ) && ! empty( $a->delivered_at ) ) { $film_count += max( 1, (int) $a->qty ); }
			if ( $a->review_state === 'review' && ! empty( $a->delivered_at ) ) { $awaiting++; }
		}
	}

	$allowed   = (int) $client->campaigns_allowed;
	$remaining = $allowed > 0 ? max( 0, $allowed - $spent ) : null;
	$days_left = mwm_rm_days_until( $client->contract_end );

	// Captures: a SERIES capture never draws down (Strategy §6).
	$cap_used = 0;
	foreach ( $captures as $cp ) { if ( (int) $cp->draws_allowance === 1 ) { $cap_used++; } }
	$cap_allowed = (int) $client->captures_allowed;

	$sh_allowed = (float) $client->studio_hours_allowed;
	$sh_used    = (float) apply_filters( 'mwm_rm_studio_hours_used', 0, $client );

	// Every figure an attention card is allowed to quote. Anything not in here
	// cannot be seeded into card copy, which is the point.
	$tok = array(
		'{campaign_days_left}'  => $remaining === null ? '' : mwm_rm_num( $remaining ),
		'{campaign_days_used}'  => mwm_rm_num( $spent ),
		'{campaign_days_total}' => mwm_rm_num( $allowed ),
		'{days_left}'           => mwm_rm_num( $days_left ),
		'{studio_hours_left}'   => mwm_rm_num( max( 0, $sh_allowed - $sh_used ) ),
		'{studio_hours_used}'   => mwm_rm_num( $sh_used ),
		'{studio_hours_total}'  => mwm_rm_num( $sh_allowed ),
		'{captures_left}'       => mwm_rm_num( max( 0, $cap_allowed - $cap_used ) ),
		'{captures_total}'      => mwm_rm_num( $cap_allowed ),
		'{films}'               => mwm_rm_num( $film_count ),
	);

	// 🔴 FIRST RUN — a client who has had nothing delivered yet.
	// Their portal must NOT open with an accounting of zeros. "0 campaigns filmed,
	// 0 films delivered" is not a status, it is twelve reminders that nothing has
	// happened, and it is the fastest way to make a paying client feel behind.
	// Same failure as padlocking a studio client's year (Spec §11.2).
	// So when nothing has happened yet, the page gets ONE job: book the first day.
	$first_run = ( $spent === 0 && $film_count === 0 );

	// Computed once, up here, because two sections read it and the year list must
	// not depend on the booking form having rendered first.
	$bookable = array();
	foreach ( $campaigns as $c ) {
		if ( $c->status === 'planned' && $c->shoot_state === 'none' ) { $bookable[] = $c; }
	}

	// The conversion offer surfaces itself when it is relevant (Spec §10.8.4).
	// The VALVE opens in the final 60 days (Strategy §7). The PROMPT surfaces sooner —
	// a client who finds out at day 59 has already lost the chance to just film them.
	$show_conversion = ( $remaining !== null && $remaining > 0 && $days_left !== null && $days_left <= 120 );
	?>
<div class="mwmrm" data-theme="light">

  <div class="rm-top">
    <div>
      <div class="rm-brand">MWM ROADMAP<sup>™</sup></div>
      <h1 class="rm-h1"><?php echo esc_html( $client->company ? $client->company : $client->client_name ); ?></h1>
      <p class="rm-plan">
        <?php echo esc_html( ucfirst( $client->plan ) ); ?> plan
        <?php if ( $allowed > 0 ) : ?>· <?php echo (int) $allowed; ?> campaigns<?php endif; ?>
        <?php if ( $client->contract_end ) : ?>· through <?php echo esc_html( mwm_rm_fmt_date( $client->contract_end, 'j F Y' ) ); ?><?php endif; ?>
        <?php if ( $client->strategist ) : ?>· your strategist is <?php echo esc_html( $client->strategist ); ?><?php endif; ?>
      </p>
    </div>
    <div class="rm-topr">
      <button class="rm-ghost" type="button" onclick="mwmRmTheme(this)">Light / dark</button>
      <a class="rm-ghost" href="<?php echo esc_url( add_query_arg( 'mwm_rm_logout', 1 ) ); ?>">Sign out</a>
    </div>
  </div>

  <?php if ( empty( $campaigns ) ) : ?>
    <div class="rm-note">Your roadmap is being prepared. It will appear here as soon as your strategist has finished it.</div>
  <?php else : ?>

  <!-- ── FIRST RUN: one job, not a scoreboard ─────────────────────── -->
  <?php if ( $first_run ) : ?>
  <section class="rm-sec">
    <div class="rm-hero">
      <div class="rm-heroh">Your year starts with one day.</div>
      <p class="rm-heros">
        <?php echo (int) $allowed; ?> campaigns have been planned for you and nothing has been
        filmed yet — so there is only one thing on this page that matters, and it is picking
        the first day.
      </p>

      <div class="rm-comes">
        <div class="rm-comesh">We come to you</div>
        <p>You do not need to travel to a studio or give up a weekend. We bring the cameras,
          the lighting, the sound and the teleprompter to <b>your own office</b> and film there.
          It is a better setting for what you are explaining, and it costs you a few hours
          instead of a day.</p>
      </div>

      <div class="rm-what">
        <div class="rm-whath">What a campaign is</div>
        <p>A campaign is a <b>production day and everything that comes out of it</b> — the films,
          the short cuts, the versions for each platform. It is not one video. One day of filming
          usually becomes a set of finished pieces you will be publishing for weeks.</p>
      </div>
    </div>
  </section>
  <?php else : ?>
  <!-- ── AT A GLANCE ───────────────────────────────────────────────── -->
  <div class="rm-tiles">
    <div class="rm-tile">
      <div class="rm-n"><?php echo (int) $spent; ?><span class="rm-of"> / <?php echo $allowed > 0 ? (int) $allowed : '∞'; ?></span></div>
      <div class="rm-l">Campaigns filmed</div>
    </div>
    <div class="rm-tile">
      <div class="rm-n"><?php echo (int) $film_count; ?></div>
      <div class="rm-l">Films delivered to you</div>
    </div>
    <div class="rm-tile">
      <div class="rm-n"><?php echo (int) $awaiting; ?></div>
      <div class="rm-l">Waiting for your review</div>
    </div>
    <div class="rm-tile">
      <div class="rm-n"><?php echo $days_left !== null ? (int) max( 0, $days_left ) : '—'; ?></div>
      <div class="rm-l">Days left in your year</div>
    </div>
  </div>

  <?php endif; ?>

  <!-- ── WHAT YOU CAN BOOK ─────────────────────────────────────────── -->
  <section class="rm-sec">
    <h2 class="rm-h2">What you can book, and how</h2>
    <div class="rm-book">
      <div class="rm-brow">
        <div class="rm-bk">Campaign day <span class="rm-bmini">in your plan</span></div>
        <div class="rm-bd">A full production day. Tell us the campaign and we will build the day around it.</div>
        <div class="rm-bn"><b>7 days'</b> notice on location<br><b>48 hours'</b> notice in the studio</div>
      </div>
      <div class="rm-brow">
        <div class="rm-bk">Capture · series <span class="rm-bmini">does not draw down</span></div>
        <div class="rm-bd">Somewhere you want filmed more than once as it changes — a project, a site, a space being built or renovated. Register it once and we plan it into our route.</div>
        <div class="rm-bn">We schedule it with you</div>
      </div>
      <div class="rm-brow">
        <div class="rm-bk">Capture · standard <span class="rm-bmini">draws 1</span></div>
        <div class="rm-bd">Tell us the place. We choose the day and group it with other visits nearby.</div>
        <div class="rm-bn">Filmed within <b>10 working days</b></div>
      </div>
      <div class="rm-brow">
        <div class="rm-bk">Studio hours <span class="rm-bmini">in your plan</span></div>
        <div class="rm-bd">Our studio, already lit. Good for talking-head pieces, interviews and social sets.</div>
        <div class="rm-bn"><b>48 hours'</b> notice</div>
      </div>
    </div>

    <div class="rm-cost">
      <div class="rm-costh">What costs extra</div>
      <ul>
        <li><b>Priority Capture</b> — you name the day, or you need it within 5 days. That is a dedicated trip, so it is charged at our rate card and does not come out of your allowance.</li>
        <li><b>Captures beyond your allowance</b> — charged at rate card.</li>
        <li><b>Studio time beyond your included hours</b> — charged at our hourly rate.</li>
        <li><b>Moving or cancelling inside the notice window</b> — 7 days on location, 48 hours in the studio. The crew day is committed by then, so it uses up that campaign day. <b>Outside the window, changes are free.</b></li>
      </ul>
    </div>
  </section>

  <!-- ── REQUEST A FILMING DAY (spec §6) ───────────────────────────── -->
  <?php
  if ( ! empty( $bookable ) ) :
    $min_studio   = mwm_rm_earliest_open( 'studio' );
    $min_location = mwm_rm_earliest_open( 'location' );
    $last_day     = $client->contract_end ? $client->contract_end : date( 'Y-m-d', strtotime( '+1 year' ) );
  ?>
  <section class="rm-sec">
    <h2 class="rm-h2"><?php echo $first_run ? 'Book your first filming day' : 'Book your next filming day'; ?></h2>

    <?php if ( $req_ok ) : ?>
      <div class="rm-held">
        <div class="rm-heldh">We are holding <?php echo esc_html( mwm_rm_fmt_date( $req_ok['date'], 'l j F' ) ); ?> for you.</div>
        <p>That day is now off the calendar for everyone else while we look at it.
           <strong>It is not confirmed yet</strong> — <?php echo esc_html( $client->strategist ? $client->strategist : 'your strategist' ); ?>
           will come back to you, and you will see it change to Confirmed right here.</p>
      </div>
    <?php endif; ?>

    <?php if ( $req_error ) : ?>
      <div class="rm-err" role="alert"><?php echo esc_html( $req_error ); ?></div>
    <?php endif; ?>

    <form method="post" class="rm-book-form" id="rm-book"
          data-min-studio="<?php echo esc_attr( $min_studio ); ?>"
          data-min-location="<?php echo esc_attr( $min_location ); ?>">
      <?php wp_nonce_field( 'mwm_rm_request', 'mwm_rm_rnonce' ); ?>

      <!-- 🔴 Shoot type comes FIRST because it changes which days exist. -->
      <div class="rm-f">
        <label class="rm-flab">Where are we filming?</label>
        <div class="rm-seg">
          <label class="rm-segopt">
            <input type="radio" name="shoot_kind" value="location" checked>
            <span><b>On location</b><em>Your office, a site, wherever the story is</em></span>
          </label>
          <label class="rm-segopt">
            <input type="radio" name="shoot_kind" value="studio">
            <span><b>In our studio</b><em>Already lit and ready for you</em></span>
          </label>
        </div>
        <div class="rm-rule" id="rm-rule"></div>
      </div>

      <div class="rm-grid2">
        <div class="rm-f">
          <label class="rm-flab" for="rm-date">Which day?</label>
          <input class="rm-in" type="date" name="shoot_date" id="rm-date" required
                 min="<?php echo esc_attr( $min_location ); ?>" max="<?php echo esc_attr( $last_day ); ?>">
          <div class="rm-hint">Sundays are closed.</div>
        </div>
        <div class="rm-f">
          <label class="rm-flab" for="rm-window">What time?</label>
          <select class="rm-in" name="window" id="rm-window" required>
            <?php foreach ( mwm_rm_windows() as $k => $w ) : ?>
              <option value="<?php echo esc_attr( $k ); ?>"><?php echo esc_html( $w['label'] ); ?></option>
            <?php endforeach; ?>
          </select>
        </div>
      </div>

      <div class="rm-f" id="rm-addr-wrap">
        <label class="rm-flab" for="rm-addr">Full address</label>
        <input class="rm-in" type="text" name="address" id="rm-addr" placeholder="Street, city, ZIP — gate codes go in the notes">
        <div class="rm-hint">We need the whole address so the crew can get there without calling you.</div>
      </div>

      <div class="rm-f">
        <label class="rm-flab" for="rm-campaign">Which campaign is this day for?</label>
        <select class="rm-in" name="campaign_id" id="rm-campaign" required>
          <?php foreach ( $bookable as $c ) : ?>
            <option value="<?php echo (int) $c->id; ?>">Campaign <?php echo (int) $c->month_no; ?> · <?php echo esc_html( $c->title ); ?></option>
          <?php endforeach; ?>
        </select>
      </div>

      <div class="rm-f">
        <label class="rm-flab" for="rm-notes">Anything we should know? <span class="rm-opt">Optional</span></label>
        <textarea class="rm-in" name="notes" id="rm-notes" rows="3"
                  placeholder="Who is on camera, gate codes, parking, guests to invite, anything happening that day"></textarea>
      </div>

      <div class="rm-actions">
        <button class="rm-btn" type="submit" name="mwm_rm_request" value="1">Request this day</button>
        <span class="rm-actnote">This holds the day and sends it to us. <strong>It is not booked until we confirm</strong> — you will see it change here.</span>
      </div>
    </form>
  </section>

  <script>
  (function(){
    var f = document.getElementById('rm-book'); if(!f) return;
    var date = document.getElementById('rm-date'),
        rule = document.getElementById('rm-rule'),
        addr = document.getElementById('rm-addr-wrap'),
        addrIn = document.getElementById('rm-addr');
    // 🔴 The minimums come from PHP. The browser never computes the notice rule.
    var mins = { studio: f.dataset.minStudio, location: f.dataset.minLocation };
    function human(s){
      var d = new Date(s + 'T12:00:00');
      return d.toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'long'});
    }
    function apply(){
      var kind = f.querySelector('input[name=shoot_kind]:checked').value;
      date.min = mins[kind];
      if (date.value && date.value < date.min) { date.value = ''; }
      rule.textContent = (kind === 'studio')
        ? 'Studio days need 48 hours\u2019 notice — the earliest we can take is ' + human(mins.studio) + '.'
        : 'Filming on location needs 7 days\u2019 notice — the earliest we can take is ' + human(mins.location) + '.';
      var loc = (kind === 'location');
      addr.style.display = loc ? '' : 'none';
      addrIn.required = loc;
    }
    f.querySelectorAll('input[name=shoot_kind]').forEach(function(r){ r.addEventListener('change', apply); });
    apply();
  })();
  </script>
  <?php endif; ?>

  <!-- ── NEXT FILMING SESSION ──────────────────────────────────────── -->
  <?php if ( $next ) :
    $conf = mwm_rm_confirmations( $next,
      isset( $people_by[ (int) $next->id ] ) ? $people_by[ (int) $next->id ] : array(),
      isset( $assets_by[ (int) $next->id ] ) ? $assets_by[ (int) $next->id ] : array() );
    $open = 0; foreach ( $conf as $c2 ) { if ( ! $c2['done'] ) { $open++; } } ?>
  <section class="rm-sec">
    <h2 class="rm-h2">Your next filming session</h2>
    <div class="rm-next">
      <div class="rm-nexthead">
        <div>
          <div class="rm-nextdate"><?php echo esc_html( mwm_rm_fmt_date( $next->shoot_at, 'l j F' ) ); ?></div>
          <div class="rm-nextsub">
            <?php echo esc_html( mwm_rm_fmt_date( $next->shoot_at, 'g:ia' ) ); ?>
            <?php if ( $next->shoot_location ) : ?>· <?php echo esc_html( $next->shoot_location ); ?><?php endif; ?>
            · <?php echo esc_html( $next->title ); ?>
          </div>
        </div>
        <span class="rm-pill <?php echo $next->shoot_state === 'confirmed' ? 'rm-p3' : 'rm-p2'; ?>">
          <?php echo $next->shoot_state === 'confirmed' ? 'Confirmed' : 'Holding this date'; ?>
        </span>
      </div>

      <div class="rm-confhead"><?php echo $open === 0
        ? 'Everything is confirmed — nothing needed from you.'
        : 'Before this day we need ' . (int) $open . ' ' . ( $open === 1 ? 'thing' : 'things' ) . ' from you.'; ?></div>

      <div class="rm-conf">
        <?php foreach ( $conf as $c2 ) : ?>
          <div class="rm-citem <?php echo $c2['done'] ? 'is-done' : 'is-open'; ?>">
            <span class="rm-cmark" aria-hidden="true"><?php echo $c2['done'] ? '✓' : '!'; ?></span>
            <span class="rm-ck"><?php echo esc_html( $c2['label'] ); ?></span>
            <span class="rm-cv"><?php echo esc_html( $c2['value'] ); ?></span>
          </div>
        <?php endforeach; ?>
      </div>
    </div>
  </section>
  <?php elseif ( ! $first_run ) : ?>
  <section class="rm-sec">
    <h2 class="rm-h2">Your next filming session</h2>
    <div class="rm-next rm-nextempty">
      <div class="rm-nextdate">Nothing booked yet</div>
      <div class="rm-nextsub">
        <?php if ( $remaining !== null && $remaining > 0 && $days_left !== null ) : ?>
          You have <strong><?php echo (int) $remaining; ?></strong> campaign <?php echo $remaining === 1 ? 'day' : 'days'; ?>
          and <strong><?php echo (int) max( 0, $days_left ); ?></strong> days left in your year.
          Pick a day above and we will get it in the diary.
        <?php else : ?>
          Speak to your strategist to plan your next filming day.
        <?php endif; ?>
      </div>
      <div class="rm-nextrule">On location we need <b>7 days'</b> notice; in the studio, <b>48 hours'</b>.</div>
    </div>
  </section>
  <?php endif; ?>

  <!-- ── NEEDS YOUR ATTENTION ──────────────────────────────────────── -->
  <?php if ( ! empty( $actions ) ) : ?>
  <section class="rm-sec">
    <h2 class="rm-h2">Needs your attention</h2>
    <div class="rm-acts">
      <?php foreach ( $actions as $a ) :
        $age = $a->created_at ? max( 0, (int) round( ( current_time( 'timestamp' ) - strtotime( $a->created_at ) ) / DAY_IN_SECONDS ) ) : null; ?>
        <div class="rm-act">
          <div>
            <div class="rm-actt"><?php echo esc_html( mwm_rm_fill( $a->title, $tok ) ); ?></div>
            <?php if ( $a->detail ) : ?><div class="rm-actd"><?php echo esc_html( mwm_rm_fill( $a->detail, $tok ) ); ?></div><?php endif; ?>
          </div>
          <div class="rm-actage"><?php
            // An age of "0 days" is noise on something raised today. Say nothing.
            if ( $a->due_date ) { echo 'by ' . esc_html( mwm_rm_fmt_date( $a->due_date, 'j M' ) ); }
            elseif ( $age !== null && $age > 0 ) { echo (int) $age . ( $age === 1 ? ' day' : ' days' ); }
          ?></div>
        </div>
      <?php endforeach; ?>
    </div>
  </section>
  <?php endif; ?>


  <!-- ── ALLOWANCES ────────────────────────────────────────────────── -->
  <section class="rm-sec">
    <h2 class="rm-h2">What you have left</h2>
    <div class="rm-allow">
      <?php
      $meters = array();
      if ( $allowed > 0 ) {
        $meters[] = array( 'Campaign days', $spent, $allowed, 'A full production day — crew, direction and the edit that follows.' );
      }
      if ( $cap_allowed > 0 ) {
        $meters[] = array( 'Captures', $cap_used, $cap_allowed, 'A short visit to pick up footage while something is happening — one operator, in and out.' );
      }
      if ( $sh_allowed > 0 ) {
        $meters[] = array( 'Studio hours', $sh_used, $sh_allowed, 'Time in our studio, already lit and ready.' );
      }
      foreach ( $meters as $m ) :
        list( $label, $used, $total, $desc ) = $m;
        $pct = $total > 0 ? min( 100, ( $used / $total ) * 100 ) : 0;
        $left = max( 0, $total - $used ); ?>
        <div class="rm-mtr">
          <div class="rm-mtop">
            <span class="rm-mlab"><?php echo esc_html( $label ); ?></span>
            <span class="rm-mval"><strong><?php echo esc_html( rtrim( rtrim( number_format( $left, 1 ), '0' ), '.' ) ); ?></strong> left of <?php echo esc_html( rtrim( rtrim( number_format( $total, 1 ), '0' ), '.' ) ); ?></span>
          </div>
          <div class="rm-bar"><i style="width:<?php echo esc_attr( $pct ); ?>%"></i></div>
          <div class="rm-mdesc"><?php echo esc_html( $desc ); ?></div>
        </div>
      <?php endforeach; ?>
    </div>

    <?php if ( $show_conversion ) : ?>
      <div class="rm-offer">
        <strong>You have <?php echo (int) $remaining; ?> campaign <?php echo $remaining === 1 ? 'day' : 'days'; ?> and <?php echo (int) $days_left; ?> days to use them.</strong>
        If some will not fit before your year ends, an unused campaign day can become
        <strong>6 studio hours</strong> or <strong>2 Captures</strong> instead. Ask your strategist and we will set it up.
      </div>
    <?php endif; ?>
  </section>

  <!-- ── THE YEAR ──────────────────────────────────────────────────── -->
  <section class="rm-sec">
    <h2 class="rm-h2"><?php echo $first_run ? 'What we are going to make' : 'Your year'; ?></h2>
    <?php if ( $first_run ) : ?>
      <p class="rm-yearlede">Your strategist wrote this arc for you. The order matters — each
        campaign is built on the one before it — but <b>you choose when each one happens, where,
        who is in it and what it says.</b> Nothing here is fixed except the thinking behind it.</p>
    <?php endif; ?>
    <div class="rm-year">
      <?php foreach ( $campaigns as $c ) :
        $ca   = isset( $assets_by[ (int) $c->id ] ) ? $assets_by[ (int) $c->id ] : array();
        $step = mwm_rm_status_step( $c->status );
        $films = array();
        foreach ( $ca as $a ) { if ( $a->kind !== 'script' ) { $films[] = $a; } } ?>
        <details class="rm-cam" <?php echo ( $c->status === 'editing' || ( $next && $c->id === $next->id ) ) ? 'open' : ''; ?>>
          <summary class="rm-camsum">
            <span class="rm-cmonth">Campaign <?php echo (int) $c->month_no; ?></span>
            <span class="rm-ctitle"><?php echo esc_html( $c->title ); ?></span>
            <?php if ( $first_run && ! empty( $bookable ) && (int) $c->id === (int) $bookable[0]->id ) : ?>
              <span class="rm-pill rm-pstart">Start here</span>
            <?php else : ?>
              <span class="rm-pill rm-p<?php echo (int) $step; ?>"><?php echo esc_html( mwm_rm_status_label( $c->status ) ); ?></span>
            <?php endif; ?>
          </summary>
          <div class="rm-cambody">
            <?php if ( $c->theme_desc ) : ?><p class="rm-ctheme"><?php echo esc_html( $c->theme_desc ); ?></p><?php endif; ?>

            <div class="rm-cmeta">
              <?php if ( ! empty( $c->shoot_at ) ) : ?>
                <span><b>Filmed</b> <?php echo esc_html( mwm_rm_fmt_date( $c->shoot_at, 'j M Y' ) ); ?></span>
              <?php endif; ?>
              <?php if ( ! empty( $c->shoot_location ) ) : ?>
                <span><b>Where</b> <?php echo esc_html( $c->shoot_location ); ?></span>
              <?php endif; ?>
              <?php if ( ! empty( $c->delivered_at ) ) : ?>
                <span><b>Delivered</b> <?php echo esc_html( mwm_rm_fmt_date( $c->delivered_at, 'j M Y' ) ); ?></span>
              <?php endif; ?>
            </div>

            <?php if ( ! empty( $films ) ) : ?>
              <ul class="rm-films">
                <?php foreach ( $films as $a ) : ?>
                  <li>
                    <?php if ( $a->url ) : ?>
                      <a href="<?php echo esc_url( $a->url ); ?>" target="_blank" rel="noopener"><?php echo esc_html( $a->title ); ?></a>
                    <?php else : ?>
                      <span><?php echo esc_html( $a->title ); ?></span>
                    <?php endif; ?>
                    <?php if ( (int) $a->qty > 1 ) : ?><em>×<?php echo (int) $a->qty; ?></em><?php endif; ?>
                    <?php if ( $a->review_state === 'review' && $a->delivered_at ) : ?>
                      <span class="rm-mini rm-mini-b">Awaiting your review</span>
                    <?php elseif ( $a->review_state === 'approved' ) : ?>
                      <span class="rm-mini rm-mini-g">Approved</span>
                    <?php elseif ( $a->review_state === 'fix' ) : ?>
                      <span class="rm-mini rm-mini-a">Changes requested</span>
                    <?php endif; ?>
                  </li>
                <?php endforeach; ?>
              </ul>
            <?php elseif ( $c->status === 'planned' ) : ?>
              <p class="rm-cempty">Not filmed yet — this campaign is still yours.</p>
            <?php elseif ( $c->status === 'editing' ) : ?>
              <p class="rm-cempty">In the edit now. We will let you know the moment it is ready for you.</p>
            <?php endif; ?>
          </div>
        </details>
      <?php endforeach; ?>
    </div>
  </section>

  <p class="rm-foot">
    Questions about any of this? Email <a href="mailto:info@mwmcreations.com">info@mwmcreations.com</a> or speak to your strategist.
  </p>

  <?php endif; ?>
</div>

<script>
function mwmRmTheme(btn){
  var r = btn.closest('.mwmrm');
  r.dataset.theme = r.dataset.theme === 'dark' ? 'light' : 'dark';
}
(function(){
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    document.querySelectorAll('.mwmrm').forEach(function(r){ r.dataset.theme='dark'; });
  }
})();
</script>
<?php }

/* ===========================================================================
 * STYLES — scoped to .mwmrm so nothing leaks into the theme
 * Ordinal status ramp validated in both modes (single hue, monotone lightness,
 * adjacent ΔL >= 0.06, light end clears 2:1 on its surface). Every pill also
 * carries a text label — colour never carries meaning alone.
 * ======================================================================== */

function mwm_rm_styles() {
	ob_start(); ?>
<style>
/* Widen only the page that carries the portal. Scoped by the body class added
   above, so no other page on the site is affected. */
body.mwm-roadmap-page .page-content,
body.mwm-roadmap-page .site-main,
body.mwm-roadmap-page .entry-content,
body.mwm-roadmap-page .content-area{max-width:1200px !important;width:100% !important}

.mwmrm{
  --su:#fcfcfb;--pa:#fff;--p2:#f6f6f4;--ln:#e4e3df;
  --ink:#1a1a19;--i2:#57564f;--i3:#86857c;
  --s1:#86b6ef;--s2:#5598e7;--s3:#2a78d6;--s4:#1c5cab;--s5:#104281;
  --gd:#0ca30c;--wn:#fab219;--cr:#d03b3b;
  --sh:0 1px 2px rgba(26,26,25,.06),0 4px 14px rgba(26,26,25,.05);
  background:var(--su);color:var(--ink);
  font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Inter,system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;
  max-width:1120px;margin:0 auto;padding:30px 20px 70px;box-sizing:border-box;
}
.mwmrm[data-theme="dark"]{
  --su:#1a1a19;--pa:#232322;--p2:#2b2b29;--ln:#383835;
  --ink:#f4f4f1;--i2:#b6b5ad;--i3:#86857c;
  --s1:#184f95;--s2:#256abf;--s3:#3987e5;--s4:#6da7ec;--s5:#9ec5f4;
  --sh:0 1px 2px rgba(0,0,0,.4),0 4px 16px rgba(0,0,0,.3);
}
.mwmrm *{box-sizing:border-box}
.mwmrm h1,.mwmrm h2,.mwmrm p,.mwmrm ul,.mwmrm li{margin:0;padding:0}
.mwmrm ul{list-style:none}
.mwmrm a{color:var(--s3);text-decoration:none}
.mwmrm[data-theme="dark"] a{color:var(--s4)}
.mwmrm a:hover{text-decoration:underline}

/* login */
.rm-login{max-width:400px;margin:40px auto;background:var(--pa);border:1px solid var(--ln);
  border-radius:14px;padding:32px 30px;box-shadow:var(--sh)}
.rm-lbrand{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--i3);font-weight:700}
.rm-ltitle{font-size:25px;font-weight:670;letter-spacing:-.02em;margin:9px 0 7px !important;line-height:1.2}
.rm-lsub{font-size:13.6px;color:var(--i2);margin-bottom:20px !important}
.rm-lform{display:flex;flex-direction:column}
.rm-lab{font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--i3);font-weight:660;margin-bottom:6px}
.rm-in{width:100%;padding:11px 13px;border:1px solid var(--ln);border-radius:9px;background:var(--su);
  color:var(--ink);font-size:15px;margin-bottom:16px;font-family:inherit}
.rm-in:focus{outline:2px solid var(--s3);outline-offset:1px;border-color:var(--s3)}
.rm-code{letter-spacing:.34em;text-transform:uppercase;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.rm-btn{width:100%;padding:12px 16px;border:0;border-radius:9px;background:var(--s4);color:#fff;
  font-size:15px;font-weight:640;cursor:pointer;font-family:inherit}
.mwmrm[data-theme="dark"] .rm-btn{background:var(--s3)}
.rm-btn:hover{background:var(--s5)}
.mwmrm[data-theme="dark"] .rm-btn:hover{background:var(--s4);color:#0d2440}
.rm-err{background:color-mix(in srgb,var(--cr) 10%,var(--pa));border:1px solid color-mix(in srgb,var(--cr) 40%,var(--ln));
  color:var(--cr);border-radius:9px;padding:11px 13px;font-size:13.4px;margin-bottom:16px;font-weight:560}
.rm-lfoot{font-size:12.4px;color:var(--i3);margin-top:18px !important;line-height:1.55}



/* first run — the welcome hero */
.rm-hero{background:var(--pa);border:1px solid var(--ln);border-radius:14px;padding:26px 28px;box-shadow:var(--sh);
  background-image:linear-gradient(180deg,color-mix(in srgb,var(--s1) 13%,var(--pa)) 0%,var(--pa) 42%)}
html[data-theme="dark"] .rm-hero{background-image:linear-gradient(180deg,color-mix(in srgb,var(--s1) 40%,var(--pa)) 0%,var(--pa) 42%)}
@media(max-width:620px){.rm-hero{padding:22px 18px}}
.rm-heroh{font-size:28px;font-weight:680;letter-spacing:-.028em;line-height:1.16;max-width:22ch}
@media(max-width:560px){.rm-heroh{font-size:23px}}
.rm-heros{font-size:15.5px;color:var(--i2);line-height:1.62;margin-top:10px;max-width:60ch}
.rm-comes,.rm-what{margin-top:18px;background:var(--p2);border:1px solid var(--ln);border-radius:11px;padding:15px 17px}
html[data-theme="dark"] .rm-comes,html[data-theme="dark"] .rm-what{background:var(--su)}
.rm-comes{border-left:3px solid var(--s3)}
.rm-comesh,.rm-whath{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--i3);font-weight:680;margin-bottom:7px}
.rm-comes p,.rm-what p{font-size:13.8px;color:var(--i2);line-height:1.62}
.rm-comes b,.rm-what b{color:var(--ink)}
.rm-yearlede{font-size:13.8px;color:var(--i2);line-height:1.62;margin-bottom:13px;max-width:74ch}
.rm-yearlede b{color:var(--ink)}
.rm-pstart{background:var(--gd);color:#fff}

/* booking form */
.rm-book-form{background:var(--pa);border:1px solid var(--ln);border-radius:12px;padding:20px 22px;box-shadow:var(--sh)}
.rm-f{margin-bottom:17px}
.rm-f:last-of-type{margin-bottom:0}
.rm-flab{display:block;font-size:12.4px;font-weight:660;color:var(--i2);margin-bottom:7px}
.rm-opt{font-weight:500;color:var(--i3);font-size:11.6px}
.rm-grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:620px){.rm-grid2{grid-template-columns:1fr;gap:0}}
.rm-book-form .rm-in{width:100%;padding:11px 13px;border:1px solid var(--ln);border-radius:9px;
  background:var(--su);color:var(--ink);font-size:15px;font-family:inherit;margin-bottom:0}
.rm-book-form textarea.rm-in{resize:vertical;line-height:1.5}
.rm-hint{font-size:12px;color:var(--i3);margin-top:6px}
.rm-seg{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:620px){.rm-seg{grid-template-columns:1fr}}
.rm-segopt{position:relative;display:block;cursor:pointer}
.rm-segopt input{position:absolute;opacity:0;width:0;height:0}
.rm-segopt span{display:block;border:1px solid var(--ln);border-radius:10px;padding:12px 14px;background:var(--su)}
.rm-segopt b{display:block;font-size:14px;font-weight:640}
.rm-segopt em{display:block;font-style:normal;font-size:12.2px;color:var(--i3);margin-top:3px}
.rm-segopt input:checked + span{border-color:var(--s3);box-shadow:inset 0 0 0 1px var(--s3);background:color-mix(in srgb,var(--s1) 12%,var(--pa))}
html[data-theme="dark"] .rm-segopt input:checked + span{background:color-mix(in srgb,var(--s1) 34%,var(--pa))}
.rm-segopt input:focus-visible + span{outline:2px solid var(--s3);outline-offset:2px}
.rm-rule{margin-top:11px;font-size:12.8px;color:var(--i2);background:var(--p2);border:1px solid var(--ln);
  border-left:3px solid var(--s3);border-radius:8px;padding:10px 12px}
.rm-actions{margin-top:20px;padding-top:17px;border-top:1px solid var(--ln);display:flex;align-items:center;gap:15px;flex-wrap:wrap}
.rm-btn{padding:12px 22px;border:0;border-radius:9px;background:var(--s4);color:#fff;font-size:15px;
  font-weight:640;cursor:pointer;font-family:inherit;width:auto}
html[data-theme="dark"] .rm-btn{background:var(--s3)}
.rm-btn:hover{background:var(--s5)}
html[data-theme="dark"] .rm-btn:hover{background:var(--s4);color:#0d2440}
.rm-actnote{font-size:12.6px;color:var(--i3);max-width:44ch;line-height:1.5}
.rm-actnote strong{color:var(--i2)}
.rm-held{background:var(--pa);border:1px solid var(--ln);border-left:3px solid var(--gd);border-radius:11px;
  padding:15px 17px;margin-bottom:14px;box-shadow:var(--sh)}
.rm-heldh{font-size:17px;font-weight:650;letter-spacing:-.012em;margin-bottom:5px}
.rm-held p{font-size:13.4px;color:var(--i2);line-height:1.6}
.rm-held strong{color:var(--ink)}

/* header */
.rm-top{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;flex-wrap:wrap;margin-bottom:24px}
.rm-brand{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--i3);font-weight:700}
.rm-h1{font-size:30px;font-weight:680;letter-spacing:-.025em;margin:5px 0 5px !important;line-height:1.15}
.rm-plan{font-size:13.6px;color:var(--i2)}
.rm-topr{display:flex;gap:8px;flex-wrap:wrap}
.rm-ghost{border:1px solid var(--ln);background:var(--pa);color:var(--i2);border-radius:999px;
  padding:7px 14px;font-size:12.5px;font-weight:560;cursor:pointer;font-family:inherit;text-decoration:none;white-space:nowrap}
.rm-ghost:hover{color:var(--ink);border-color:var(--i3);text-decoration:none}
.rm-note{background:var(--pa);border:1px solid var(--ln);border-radius:12px;padding:22px;color:var(--i2);box-shadow:var(--sh)}

/* tiles */
.rm-tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:32px}
.rm-tile{background:var(--pa);border:1px solid var(--ln);border-radius:12px;padding:16px 17px;box-shadow:var(--sh)}
.rm-n{font-size:31px;font-weight:660;letter-spacing:-.03em;line-height:1;font-variant-numeric:tabular-nums}
.rm-of{font-size:16px;color:var(--i3);font-weight:560}
.rm-l{font-size:12.6px;color:var(--i2);margin-top:8px}

/* sections */
.rm-sec{margin-bottom:32px}
.rm-h2{font-size:12px;letter-spacing:.13em;text-transform:uppercase;color:var(--i3);font-weight:680;margin-bottom:12px !important}

/* next filming */
.rm-next{background:var(--pa);border:1px solid var(--ln);border-left:3px solid var(--s3);
  border-radius:12px;padding:18px 20px;box-shadow:var(--sh)}
.rm-nexthead{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap;margin-bottom:15px}
.rm-nextdate{font-size:21px;font-weight:660;letter-spacing:-.015em}
.rm-nextsub{font-size:13.4px;color:var(--i2);margin-top:3px}
.rm-nextempty{border-left-color:var(--s1)}
.rm-nextempty .rm-nextsub{margin-top:6px;font-size:14px;line-height:1.6}
.rm-nextempty .rm-nextsub strong{color:var(--ink);font-weight:660}
.rm-nextrule{margin-top:13px;padding-top:12px;border-top:1px solid var(--ln);font-size:12.6px;color:var(--i3)}
.rm-nextrule b{color:var(--i2)}
.rm-confhead{font-size:14px;font-weight:600;padding-top:14px;border-top:1px solid var(--ln);margin-bottom:12px}
.rm-conf{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}
.rm-citem{display:flex;align-items:baseline;gap:9px;background:var(--p2);border:1px solid var(--ln);
  border-radius:9px;padding:10px 12px;min-width:0}
.rm-cmark{width:17px;height:17px;border-radius:5px;flex:none;display:inline-flex;align-items:center;
  justify-content:center;font-size:11px;font-weight:800;color:#fff;align-self:center}
.is-done .rm-cmark{background:var(--gd)}
.is-open .rm-cmark{background:var(--wn);color:#4a3200}
.rm-ck{font-size:12.6px;font-weight:660;flex:none}
.rm-cv{font-size:12.6px;color:var(--i2);overflow-wrap:break-word;min-width:0}

/* actions */
.rm-acts{display:flex;flex-direction:column;gap:9px}
.rm-act{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;background:var(--pa);
  border:1px solid var(--ln);border-left:3px solid var(--wn);border-radius:10px;padding:13px 15px;box-shadow:var(--sh)}
.rm-actt{font-size:14px;font-weight:620}
.rm-actd{font-size:13px;color:var(--i2);margin-top:3px}
.rm-actage{font-size:12.3px;color:var(--i3);white-space:nowrap;flex:none}

/* allowances */
.rm-allow{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.rm-mtr{background:var(--pa);border:1px solid var(--ln);border-radius:12px;padding:15px 16px;box-shadow:var(--sh)}
.rm-mtop{display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap}
.rm-mlab{font-size:13.4px;font-weight:640}
.rm-mval{font-size:12.6px;color:var(--i2)}
.rm-mval strong{color:var(--ink);font-size:14px}
.rm-bar{height:8px;border-radius:5px;background:var(--p2);overflow:hidden;margin:11px 0 9px}
.rm-bar i{display:block;height:100%;background:var(--s4);border-radius:5px}
.mwmrm[data-theme="dark"] .rm-bar i{background:var(--s3)}
.rm-mdesc{font-size:12.2px;color:var(--i3);line-height:1.5}
.rm-offer{margin-top:12px;background:var(--pa);border:1px solid var(--ln);border-left:3px solid var(--s3);
  border-radius:10px;padding:14px 16px;font-size:13.4px;color:var(--i2);line-height:1.6;box-shadow:var(--sh)}
.rm-offer strong{color:var(--ink)}

/* year */
.rm-year{display:flex;flex-direction:column;gap:8px}
.rm-cam{background:var(--pa);border:1px solid var(--ln);border-radius:11px;box-shadow:var(--sh);overflow:hidden}
.rm-camsum{display:flex;align-items:center;gap:13px;padding:14px 16px;cursor:pointer;list-style:none;flex-wrap:wrap}
.rm-camsum::-webkit-details-marker{display:none}
.rm-camsum:hover{background:var(--p2)}
.rm-cmonth{font-size:10.6px;letter-spacing:.1em;text-transform:uppercase;color:var(--i3);font-weight:680;
  flex:none;width:96px;white-space:nowrap}
.rm-ctitle{font-size:15px;font-weight:620;letter-spacing:-.008em;flex:1;min-width:120px}
.rm-cambody{padding:0 16px 16px 16px;border-top:1px solid var(--ln);padding-top:14px}
.rm-ctheme{font-size:13.6px;color:var(--i2);line-height:1.6}
.rm-cmeta{display:flex;flex-wrap:wrap;gap:16px;margin-top:11px;font-size:12.6px;color:var(--i2)}
.rm-cmeta b{color:var(--i3);font-weight:640;font-size:10.6px;letter-spacing:.08em;text-transform:uppercase;margin-right:5px}
.rm-films{margin-top:13px !important;display:flex;flex-direction:column;gap:7px}
.rm-films li{display:flex;align-items:center;gap:9px;font-size:13.6px;flex-wrap:wrap;
  padding:9px 12px;background:var(--p2);border-radius:8px}
.rm-films em{font-style:normal;color:var(--i3);font-size:12.4px}
.rm-cempty{margin-top:12px !important;font-size:13.2px;color:var(--i3)}
.rm-mini{font-size:10.6px;font-weight:660;padding:2px 7px;border-radius:5px;letter-spacing:.02em;white-space:nowrap}
.rm-mini-b{background:color-mix(in srgb,var(--s3) 16%,transparent);color:var(--s4)}
.mwmrm[data-theme="dark"] .rm-mini-b{color:var(--s5)}
.rm-mini-g{background:color-mix(in srgb,var(--gd) 14%,transparent);color:var(--gd)}
.rm-mini-a{background:color-mix(in srgb,var(--wn) 20%,transparent);color:#7a5200}
.mwmrm[data-theme="dark"] .rm-mini-a{color:var(--wn)}

/* pills */
.rm-pill{font-size:11.4px;font-weight:640;padding:3px 10px;border-radius:999px;white-space:nowrap;flex:none}
.rm-p1{background:var(--s1);color:#0d2440}
.rm-p2{background:var(--s2);color:#fff}
.rm-p3{background:var(--s3);color:#fff}
.rm-p4{background:var(--s4);color:#fff}
.rm-p5{background:var(--s5);color:#fff}
.mwmrm[data-theme="dark"] .rm-p1{color:#dce9fa}
.mwmrm[data-theme="dark"] .rm-p2{color:#eaf2fd}
.mwmrm[data-theme="dark"] .rm-p4,.mwmrm[data-theme="dark"] .rm-p5{color:#0d2440}

/* booking */
.rm-book{background:var(--pa);border:1px solid var(--ln);border-radius:12px;overflow:hidden;box-shadow:var(--sh)}
.rm-brow{display:grid;grid-template-columns:1fr 1.7fr .9fr;gap:16px;padding:14px 16px;border-bottom:1px solid var(--ln);align-items:start}
.rm-brow:last-child{border-bottom:none}
.rm-bk{font-size:13.6px;font-weight:640}
.rm-bmini{display:block;font-size:11.2px;font-weight:560;color:var(--i3);margin-top:2px}
.rm-bd{font-size:13px;color:var(--i2)}
.rm-bn{font-size:12.5px;color:var(--i2);text-align:right}
.rm-cost{margin-top:12px;background:var(--p2);border:1px solid var(--ln);border-radius:12px;padding:16px 18px}
.rm-costh{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--i3);font-weight:680;margin-bottom:10px}
.rm-cost ul{display:flex;flex-direction:column;gap:8px}
.rm-cost li{font-size:13px;color:var(--i2);line-height:1.6;padding-left:15px;position:relative}
.rm-cost li:before{content:"";position:absolute;left:0;top:8px;width:5px;height:5px;border-radius:2px;background:var(--i3)}
.rm-cost b{color:var(--ink)}

.rm-foot{margin-top:36px;padding-top:18px;border-top:1px solid var(--ln);font-size:12.8px;color:var(--i3)}

@media(max-width:860px){
  .rm-tiles{grid-template-columns:repeat(2,1fr)}
  .rm-allow{grid-template-columns:1fr}
  .rm-brow{grid-template-columns:1fr;gap:5px}
  .rm-bn{text-align:left}
}
@media(max-width:560px){
  .mwmrm{padding:22px 15px 55px}
  .rm-conf{grid-template-columns:1fr}
  .rm-h1{font-size:25px}
  .rm-cmonth{width:auto}
}
</style>
<?php
	return ob_get_clean();
}
