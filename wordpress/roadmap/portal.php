<?php
// Code Snippets plugin — MWM ROADMAP™ Portal · LOGIN + READ-ONLY RENDER
// WP Code Snippets ID 30 · ACTIVE · DEV · Aug 11 2026 · v1.0.2
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
	if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $bookings ) ) !== $bookings ) {
		return $default;
	}

	// Scope to the roadmap contract window when we have one, so a studio hour
	// used under last year's contract does not eat this year's allowance.
	if ( ! empty( $client->contract_start ) && ! empty( $client->contract_end ) ) {
		$used = $wpdb->get_var( $wpdb->prepare(
			"SELECT COALESCE(SUM(duration_hours),0) FROM {$bookings}
			 WHERE client_id = %d
			   AND status IN ('confirmed','completed','cancelled_late')
			   AND booking_date >= %s AND booking_date <= %s",
			(int) $client->studio_client_id, $client->contract_start, $client->contract_end
		) );
	} else {
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

	ob_start();
	echo mwm_rm_styles();
	if ( ! $client ) {
		mwm_rm_login_screen( $error );
	} else {
		mwm_rm_portal_screen( $client );
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

function mwm_rm_portal_screen( $client ) {

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
  <?php else : ?>
  <section class="rm-sec">
    <h2 class="rm-h2">Your next filming session</h2>
    <div class="rm-next rm-nextempty">
      <div class="rm-nextdate">Nothing booked yet</div>
      <div class="rm-nextsub">
        <?php if ( $remaining !== null && $remaining > 0 && $days_left !== null ) : ?>
          You have <strong><?php echo (int) $remaining; ?></strong> campaign <?php echo $remaining === 1 ? 'day' : 'days'; ?>
          and <strong><?php echo (int) max( 0, $days_left ); ?></strong> days left in your year.
          Speak to your strategist and we will get the next one in the diary.
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
            <div class="rm-actt"><?php echo esc_html( $a->title ); ?></div>
            <?php if ( $a->detail ) : ?><div class="rm-actd"><?php echo esc_html( $a->detail ); ?></div><?php endif; ?>
          </div>
          <div class="rm-actage"><?php
            if ( $a->due_date ) { echo 'by ' . esc_html( mwm_rm_fmt_date( $a->due_date, 'j M' ) ); }
            elseif ( $age !== null ) { echo (int) $age . ( $age === 1 ? ' day' : ' days' ); }
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
        $meters[] = array( 'Captures', $cap_used, $cap_allowed, 'A short on-location visit to pick up footage, one operator with a gimbal.' );
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
    <h2 class="rm-h2">Your year</h2>
    <div class="rm-year">
      <?php foreach ( $campaigns as $c ) :
        $ca   = isset( $assets_by[ (int) $c->id ] ) ? $assets_by[ (int) $c->id ] : array();
        $step = mwm_rm_status_step( $c->status );
        $films = array();
        foreach ( $ca as $a ) { if ( $a->kind !== 'script' ) { $films[] = $a; } } ?>
        <details class="rm-cam" <?php echo ( $c->status === 'editing' || ( $next && $c->id === $next->id ) ) ? 'open' : ''; ?>>
          <summary class="rm-camsum">
            <span class="rm-cmonth">Month <?php echo (int) $c->month_no; ?></span>
            <span class="rm-ctitle"><?php echo esc_html( $c->title ); ?></span>
            <span class="rm-pill rm-p<?php echo (int) $step; ?>"><?php echo esc_html( mwm_rm_status_label( $c->status ) ); ?></span>
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
              <p class="rm-cempty">Not filmed yet — this month is still yours.</p>
            <?php elseif ( $c->status === 'editing' ) : ?>
              <p class="rm-cempty">In the edit now. We will let you know the moment it is ready for you.</p>
            <?php endif; ?>
          </div>
        </details>
      <?php endforeach; ?>
    </div>
  </section>

  <!-- ── WHAT YOU CAN BOOK ─────────────────────────────────────────── -->
  <section class="rm-sec">
    <h2 class="rm-h2">What you can book, and how</h2>
    <div class="rm-book">
      <div class="rm-brow">
        <div class="rm-bk">Campaign day <span class="rm-bmini">in your plan</span></div>
        <div class="rm-bd">A full production day. Tell us the month and the theme and we will build the day around it.</div>
        <div class="rm-bn"><b>7 days'</b> notice on location<br><b>48 hours'</b> notice in the studio</div>
      </div>
      <div class="rm-brow">
        <div class="rm-bk">Capture · series <span class="rm-bmini">does not draw down</span></div>
        <div class="rm-bd">A property you want filmed repeatedly — before, during and after a build. Register it once and we plan it into our route.</div>
        <div class="rm-bn">We schedule it with you</div>
      </div>
      <div class="rm-brow">
        <div class="rm-bk">Capture · standard <span class="rm-bmini">draws 1</span></div>
        <div class="rm-bd">Name the property. We choose the day and group it with other visits nearby.</div>
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
  flex:none;width:80px;white-space:nowrap}
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
