<?php
// Code Snippets plugin — MWM ROADMAP™ Portal · ENTITLEMENT MODEL
// DEV · Sep 11 2026 · v1.0.0 · Spec: ROB in #dev, Sep 11 07:55 ET
//
// SOURCE OF TRUTH: MWM_Contrato_Plano_GOLD_MWM-LC-2026-02.pdf (Rev 5, 11 Sep
// 2026), §1–§6 plus the Terms of Service appended as pages 5–6. Read the PDF,
// not the /order/ card copy — ROB was explicit that the card copy is stale and
// in one place (§7) contradicts the signed ToS outright.
//
// WHY THIS FILE IS PURE
// No WordPress, no $wpdb, no globals. Every function takes its inputs and
// returns a value, so the rules can be linted and unit-tested with `php` alone
// — which is the only way to prove the one rule below that carries real money.
//
// ══════════════════════════════════════════════════════════════════════════
// 🔴 THE RULE THAT SHAPES THIS WHOLE FILE
//
// Every delivery number in the contract is "até" / "up to". They are CEILINGS,
// NOT QUOTAS. ROB: "THE PORTAL MUST NEVER RENDER THESE AS A BALANCE OWED. A
// counter like that creates an obligation on screen that the signed contract
// does not create, and a client will hold us to the screen, not the PDF."
//
// So this is enforced STRUCTURALLY, not by remembering:
//
//   · mwm_rm_delivered_summary() counts what was delivered. It does not accept
//     a ceiling argument. There is no parameter to subtract from.
//   · mwm_rm_delivery_ceilings() returns maxima for INTERNAL planning and is
//     flagged internal_only. It never meets the delivered counts in one
//     function, so "20 − 18 = 2 remaining" has nowhere to be computed.
//
// If a future change makes those two meet, the test suite fails on purpose.
//
// ── the distinction that matters, and it is not a technicality ──
// HOURS are different from CEILINGS, and the portal treats them differently:
//   · Hours are a real, contracted allowance (§1: "até 4 h" studio + "até 4 h"
//     external, monthly, non-cumulative). They expire. Telling the client what
//     is left is in HER interest — silence is what makes unused hours expire.
//     So hours ARE shown as remaining.
//   · Delivery ceilings are a cap on our obligation, not a promise of volume.
//     Showing them as remaining invents a debt. So they are NEVER shown that way.
// ══════════════════════════════════════════════════════════════════════════

if ( ! defined( 'MWM_RM_ENTITLEMENT' ) ) {
define( 'MWM_RM_ENTITLEMENT', '1.0.0' );

// ── §3 · TRAVEL ZONES ─────────────────────────────────────────────────────
// Travel Policy, one way from Orlando (ZIP 32835). Identical for every client,
// so it lives in one place and is read, never retyped into a client row.
// Fee covers vehicle, fuel, wear, equipment transport, coordination.
// EXCLUDES tolls, parking and lodging — those are billed at cost.
function mwm_rm_travel_zones( $version = 'v1.1' ) {
	return array(
		'version' => $version,
		'origin'  => 'Orlando, FL 32835',
		'basis'   => 'one way',
		'excludes'=> array( 'tolls', 'parking', 'lodging' ),
		'zones'   => array(
			array( 'zone' => 1, 'min_mi' => 0,   'max_mi' => 30,   'fee_cents' => 0,      'included' => true,  'label' => '0 to 30 miles' ),
			array( 'zone' => 2, 'min_mi' => 31,  'max_mi' => 75,   'fee_cents' => 30000,  'included' => false, 'label' => '31 to 75 miles' ),
			array( 'zone' => 3, 'min_mi' => 76,  'max_mi' => 150,  'fee_cents' => 60000,  'included' => false, 'label' => '76 to 150 miles — Tampa, Jacksonville' ),
			array( 'zone' => 4, 'min_mi' => 151, 'max_mi' => 250,  'fee_cents' => 100000, 'included' => false, 'label' => '151 to 250 miles — Miami, Fort Lauderdale, Naples' ),
			array( 'zone' => 5, 'min_mi' => 251, 'max_mi' => null, 'fee_cents' => null,   'included' => false, 'label' => 'over 250 miles, or requiring a flight', 'quote_only' => true ),
		),
	);
}

// Returns the zone row for a distance, or null when the distance is unusable.
// 🔴 Fails to null rather than to zone 1. An unknown distance must never
// silently price as "included" — that is a $1,000 mistake wearing a default.
function mwm_rm_zone_for_miles( $miles, $version = 'v1.1' ) {
	if ( $miles === null || $miles === '' || ! is_numeric( $miles ) || $miles < 0 ) {
		return null;
	}
	$miles = (float) $miles;
	foreach ( mwm_rm_travel_zones( $version )['zones'] as $z ) {
		if ( $miles >= $z['min_mi'] && ( $z['max_mi'] === null || $miles <= $z['max_mi'] ) ) {
			return $z;
		}
	}
	return null;
}

// ── §5 · ADD-ON RATE CARD, VERSIONED ──────────────────────────────────────
// ToS §13: "Pricing changes apply to new subscriptions only." A client on a
// signed agreement keeps the rates she signed, so the subscription row carries
// a rate_card_version and this function is asked for THAT version. Never read
// "the current price" for an existing client — that is how a signed rate
// quietly becomes a different one.
//
// 'annual' is the price for a client already on the annual roadmap plan.
// 'standalone' is the price for someone who is not. null means the line is not
// offered on that basis at all.
//
// 🔑 ROB: "make this data, versioned, never hardcoded". The array below is the
// SEED and the offline fallback — the shipped copy of what was signed. In
// WordPress a resolver is installed that reads wp_mwm_roadmap_rate_cards
// instead, so Michael can add a 2027 card without a code deploy. The rules in
// this file never know which one answered, which is the point: the rules are
// code, the prices are data.
function mwm_rm_set_card_resolver( $fn ) {
	$GLOBALS['mwm_rm_card_resolver'] = is_callable( $fn ) ? $fn : null;
}

function mwm_rm_rate_card( $version = '2026-09' ) {
	if ( ! empty( $GLOBALS['mwm_rm_card_resolver'] ) ) {
		$card = call_user_func( $GLOBALS['mwm_rm_card_resolver'], $version );
		// A resolver that answers nothing falls back to the shipped card rather
		// than pricing at zero. An empty table must never mean "free".
		if ( is_array( $card ) && ! empty( $card['items'] ) ) { return $card; }
	}
	return mwm_rm_shipped_rate_card( $version );
}

function mwm_rm_shipped_rate_card( $version = '2026-09' ) {
	// ROB stamped rate_card_version = "MWM-LC-2026-02-Rev5" on the live Stripe
	// subscription before this file existed. The subscription is the record of
	// what she is on, so its spelling wins and '2026-09' becomes the alias —
	// not the other way round. Two names for one card is survivable; a lookup
	// that misses and silently prices at list is not.
	$alias = array( 'MWM-LC-2026-02-Rev5' => '2026-09', 'MWM-LC-2026-02' => '2026-09' );
	if ( isset( $alias[ $version ] ) ) { $version = $alias[ $version ]; }

	$cards = array(
		'2026-09' => array(
			'version'      => '2026-09',
			'effective'    => '2026-09-11',
			'contract_ref' => 'MWM-LC-2026-02 Rev 5',
			'currency'     => 'USD',
			'items'        => array(
				'studio_hour' => array(
					'label'           => 'Additional studio hour',
					'unit'            => 'hour',
					'standalone_cents'=> 34900,
					'annual_cents'    => 24900,
					'note'            => 'Beyond the 4 studio hours included each cycle.',
					'ceilings'        => array( 'episodes' => 1, 'shorts' => 10 ), // per hour
				),
				'location_day_4h' => array(
					'label'           => 'Additional location day — up to 4 hours',
					'unit'            => 'day',
					'standalone_cents'=> null,
					'annual_cents'    => 175000,
					'note'            => 'Beyond the location day already included this cycle.',
					'ceilings'        => array( 'main_videos' => 1, 'shorts' => 10 ),
				),
				'location_day_8h' => array(
					'label'           => 'Additional location day — up to 8 hours',
					'unit'            => 'day',
					'standalone_cents'=> null,
					'annual_cents'    => 250000,
					'note'            => 'Full day.',
					'ceilings'        => array( 'main_videos' => 2, 'shorts' => 20 ),
				),
				'location_hour' => array(
					'label'           => 'Additional hour on location',
					'unit'            => 'hour',
					'standalone_cents'=> 40000,
					'annual_cents'    => 30000,
					'note'            => 'An hour beyond the contracted day, with the crew already on site.',
					'ceilings'        => array(),
				),
				'editing' => array(
					'label'           => 'Editing on add-ons',
					'unit'            => 'hour',
					'standalone_cents'=> 10000,
					'annual_cents'    => 0,          // waived — annual roadmap benefit
					'waived_on_annual'=> true,
					'note'            => 'Waived for clients on the annual roadmap plan.',
					'ceilings'        => array(),
				),
			),
			// Quoted separately, never auto-priced. Listed so the portal can say
			// so out loud instead of implying a price exists.
			'quote_only' => array(
				'Multi-day productions',
				'Special equipment',
				'Elevation / lift work',
				'Hired talent',
				'Paid location',
				'Travel zone 5 (over 250 miles, or requiring a flight)',
			),
		),
	);
	return isset( $cards[ $version ] ) ? $cards[ $version ] : null;
}

// Price one add-on line historically. Returns null when the line is not offered
// on that basis, so a caller cannot fall through to a zero.
function mwm_rm_price_addon( $version, $code, $qty = 1, $on_annual_plan = true ) {
	$card = mwm_rm_rate_card( $version );
	if ( ! $card || ! isset( $card['items'][ $code ] ) ) { return null; }
	if ( ! is_numeric( $qty ) || $qty <= 0 ) { return null; }

	$item  = $card['items'][ $code ];
	$cents = $on_annual_plan ? $item['annual_cents'] : $item['standalone_cents'];
	if ( $cents === null ) { return null; }

	return array(
		'code'          => $code,
		'label'         => $item['label'],
		'unit'          => $item['unit'],
		'qty'           => (float) $qty,
		'unit_cents'    => (int) $cents,
		'total_cents'   => (int) round( $cents * $qty ),
		'rate_card'     => $card['version'],
		'waived'        => ! empty( $item['waived_on_annual'] ) && $on_annual_plan,
	);
}

// ── §1 · THE BILLING CYCLE, AND WHY HOURS DIE IN IT ───────────────────────
// "As horas são mensais e não cumulativas — horas não utilizadas dentro do mês
// não se acumulam para o mês seguinte."
//
// 🔴 No carry-over, no banking, no grace period. ROB named all three. The cycle
// IS the window, the same rule as Studio Package Terms v1.0.
//
// The cycle is anchored to the day of the month the subscription bills on, not
// to the calendar month, because §4 says the card is charged "na mesma data de
// cada mês". A client who signs on the 14th has a cycle that runs 14th → 13th.
function mwm_rm_cycle_window( $anchor_day, $today = null ) {
	$anchor_day = (int) $anchor_day;
	if ( $anchor_day < 1 || $anchor_day > 31 ) { return null; }
	$today = $today ? $today : date( 'Y-m-d' );
	$ts    = strtotime( $today );
	if ( $ts === false ) { return null; }

	$y = (int) date( 'Y', $ts );
	$m = (int) date( 'n', $ts );
	$d = (int) date( 'j', $ts );

	// A 31st anchor in a 30-day month clamps to the last day — it does not roll
	// into the next month, which would give that client two cycles in one month.
	$clamp = function ( $yy, $mm, $day ) {
		$last = (int) date( 't', mktime( 0, 0, 0, $mm, 1, $yy ) );
		return sprintf( '%04d-%02d-%02d', $yy, $mm, min( $day, $last ) );
	};

	if ( $d >= min( $anchor_day, (int) date( 't', $ts ) ) ) {
		$start = $clamp( $y, $m, $anchor_day );
		$nm    = $m === 12 ? 1 : $m + 1;
		$ny    = $m === 12 ? $y + 1 : $y;
		$next  = $clamp( $ny, $nm, $anchor_day );
	} else {
		$pm    = $m === 1 ? 12 : $m - 1;
		$py    = $m === 1 ? $y - 1 : $y;
		$start = $clamp( $py, $pm, $anchor_day );
		$next  = $clamp( $y, $m, $anchor_day );
	}

	return array(
		'start'      => $start,
		'next_start' => $next,
		'end'        => date( 'Y-m-d', strtotime( $next . ' -1 day' ) ),
		'expires_on' => date( 'Y-m-d', strtotime( $next . ' -1 day' ) ),
	);
}

// ── §1 · INCLUDED HOURS PER CYCLE ─────────────────────────────────────────
// GOLD: one location day of up to 4 h, plus up to 4 h of studio. Up to 8 h total.
// Recording hours start when the crew ARRIVES on location — travel is not
// billed against the client's hours. (See the open question in the handoff:
// ToS §2 defines a filming day as 8 h INCLUDING travel, and §7 of the contract
// says the ToS prevail. Flagged to Michael, not resolved here.)
function mwm_rm_included_hours( $plan = 'gold' ) {
	$plans = array(
		'gold' => array(
			'location_hours' => 4.0,
			'studio_hours'   => 4.0,
			'total_hours'    => 8.0,
			'location_days'  => 1,
			'monthly_cents'  => 249700,
			'term_months'    => 12,
			'includes'       => array(
				'Concept creation for new programmes',
				'Scripts for productions made under the plan',
				'The annual content roadmap',
			),
		),
	);
	return isset( $plans[ $plan ] ) ? $plans[ $plan ] : null;
}

// What the client has left THIS cycle, and the date it dies.
// This is an allowance, not a ceiling — see the header. Showing it is correct.
function mwm_rm_hours_state( $plan, $used_location, $used_studio, $cycle ) {
	$inc = mwm_rm_included_hours( $plan );
	if ( ! $inc || ! $cycle ) { return null; }
	$ul = max( 0.0, (float) $used_location );
	$us = max( 0.0, (float) $used_studio );
	return array(
		'cycle_start'    => $cycle['start'],
		'cycle_end'      => $cycle['end'],
		'expires_on'     => $cycle['expires_on'],
		'rolls_over'     => false,   // 🔴 contract §1. Never make this true.
		'location'       => array(
			'included' => $inc['location_hours'],
			'used'     => $ul,
			'left'     => max( 0.0, $inc['location_hours'] - $ul ),
		),
		'studio'         => array(
			'included' => $inc['studio_hours'],
			'used'     => $us,
			'left'     => max( 0.0, $inc['studio_hours'] - $us ),
		),
		'counts_from'    => 'crew arrival on location',
	);
}

// ── is she actually on the plan yet? ─────────────────────────────────────
// 🔴 Luzia's GOLD term starts 3 Oct 2026, and today she is still finishing the
// $600 podcast package she is upgrading from. A portal that shows her a live
// GOLD cycle before then is showing hours she cannot yet spend, against a
// subscription she has not yet been charged for — and she signs nothing until
// the agreement comes back (Stripe: signature_status = pending).
//
// So the phase is computed, not assumed, and the page says which one she is in.
function mwm_rm_plan_phase( $term_start, $term_end = null, $today = null ) {
	$today = $today ? $today : date( 'Y-m-d' );
	if ( empty( $term_start ) ) { return 'unknown'; }
	if ( $today < $term_start ) { return 'pending'; }
	if ( $term_end && $today > $term_end ) { return 'ended'; }
	return 'active';
}

// ── §5 · SCHEDULING · TWO DIFFERENT THINGS, AND THE DIFFERENCE IS THE POINT
//
// Michael, 11 Sep 2026, correcting the first build:
//   · STUDIO is a REAL BOOKING. She picks a free slot on our calendar and it is
//     hers — no request, no approval, exactly how every other studio client
//     books today. The room is either free or it is not; there is nothing for a
//     human to decide.
//   · ON LOCATION is a REQUEST. She can see availability, but she asks. "We
//     need to go over our crew to make sure we are okay with it before
//     anything." A location day is a full crew mobilisation, and a calendar
//     that merely looks free does not mean the crew is.
//
// 🔑 That is why booking_mode exists as its own idea rather than being implied
// by the notice rule. The first build treated both as requests with different
// notice periods, which is wrong in a way that is easy to miss: it made the
// studio harder to use than it is for clients paying less.
function mwm_rm_booking_mode( $kind ) {
	$modes = array( 'studio' => 'instant', 'location' => 'request' );
	return isset( $modes[ $kind ] ) ? $modes[ $kind ] : null;
}

// ── NOTICE ────────────────────────────────────────────────────────────────
// Location: SEVEN DAYS. Michael asked for this to be checked rather than
// assumed, and the repo has one consistent answer in his own words (9 Aug 2026):
//   "at least seven days in advance if it's an exterior film shoot"
// documented at ROADMAP_Portal_Spec.md §6.2, §6.5 and ROADMAP_Strategy.md §197.
// He confirmed it on 11 Sep. No five-day rule has ever existed in this repo.
//
// Studio: NO MINIMUM. Michael, 11 Sep — the same as every other studio client.
// The live studio portal has no lead-time gate at all: same-day booking is
// allowed if the slot is free. 🔴 The ROADMAP spec's old 48-hour figure is
// SUPERSEDED for the studio and is deliberately not honoured here; keeping it
// would make a GOLD client wait two days for a room a Studio Package client can
// have this afternoon.
//
// Zero is a real answer here, not a missing one — hence the explicit array.
function mwm_rm_notice_hours( $kind ) {
	$rules = array( 'studio' => 0, 'location' => 168 );
	return array_key_exists( $kind, $rules ) ? $rules[ $kind ] : null;
}

// How far ahead either can go. 30 days matches the studio portal's
// max_advance_days, so a GOLD client sees the same horizon as everyone else.
function mwm_rm_max_advance_days( $kind = 'studio' ) {
	return $kind === 'location' ? 90 : 30;
}

// Sundays are closed by default (spec §6.3).
function mwm_rm_is_closed_day( $ymd, $closed_dows = array( 0 ) ) {
	$ts = strtotime( $ymd );
	if ( $ts === false ) { return true; }
	return in_array( (int) date( 'w', $ts ), (array) $closed_dows, true );
}

// The first date she can pick.
//
// 🔴 Three constraints, and missing any one offers her a day we would take back:
//   1. the notice rule (zero for the studio — today counts),
//   2. a closed day,
//   3. 🔑 her plan has not started. Before 3 Oct she has no GOLD hours, so a
//      date before term_start is not bookable however much notice it carries.
function mwm_rm_earliest_bookable( $kind, $today = null, $term_start = null,
                                   $closed_dows = array( 0 ), $max_scan = 60 ) {
	$notice = mwm_rm_notice_hours( $kind );
	if ( $notice === null ) { return null; }
	$today = $today ? $today : date( 'Y-m-d' );
	if ( strtotime( $today ) === false ) { return null; }

	// Whole days, rounding UP: 168 hours from some point today is seven days
	// out, and zero hours is today itself.
	$days = (int) ceil( $notice / 24 );
	$cand = $days === 0 ? $today
	        : date( 'Y-m-d', strtotime( $today . ' +' . $days . ' day' ) );

	if ( $term_start && $cand < $term_start ) { $cand = $term_start; }

	for ( $i = 0; $i < $max_scan; $i++ ) {
		if ( ! mwm_rm_is_closed_day( $cand, $closed_dows ) ) { return $cand; }
		$cand = date( 'Y-m-d', strtotime( $cand . ' +1 day' ) );
	}
	return null;
}

// 🔴 Counted from whichever is LATER: today, or the day the plan starts.
//
// Counting from today alone is wrong whenever the term has not begun, and it
// fails silently. On 11 September, with the term starting 3 October, a 30-day
// horizon from today gave a window of "3 October to 11 October" — eight days
// wide, presented as if that were the offer. Push the term start past 30 days
// and the window inverts entirely: a latest date BEFORE the earliest one, which
// renders as a sentence no client could act on and no error anyone would see.
//
// The horizon belongs to the plan, not to the calendar date someone opened the
// page on.
function mwm_rm_latest_bookable( $kind, $today = null, $term_start = null ) {
	$today = $today ? $today : date( 'Y-m-d' );
	if ( strtotime( $today ) === false ) { return null; }
	$from = ( $term_start && $term_start > $today ) ? $term_start : $today;
	return date( 'Y-m-d', strtotime( $from . ' +' . mwm_rm_max_advance_days( $kind ) . ' day' ) );
}

// The two things on the page, each carrying its own rule so the page can state
// it beside the control rather than in a paragraph nobody reads.
function mwm_rm_request_options( $client, $today = null ) {
	$term_start = isset( $client['contract_start'] ) ? $client['contract_start'] : null;
	return array(
		array(
			'kind'           => 'studio',
			'mode'           => 'instant',
			'label'          => 'Studio time',
			'where'          => 'MWM Studios, Orlando',
			'notice_hours'   => 0,
			'notice_words'   => 'no minimum — today counts if a slot is free',
			'included_hours' => 4.0,
			'earliest'       => mwm_rm_earliest_bookable( 'studio', $today, $term_start ),
			'latest'         => mwm_rm_latest_bookable( 'studio', $today, $term_start ),
			'needs_address'  => false,
			'needs_approval' => false,
			'verb'           => 'Book',
		),
		array(
			'kind'           => 'location',
			'mode'           => 'request',
			'label'          => 'Filming on location',
			'where'          => 'Your location',
			'notice_hours'   => 168,
			'notice_words'   => '7 days',
			'included_hours' => 4.0,
			'earliest'       => mwm_rm_earliest_bookable( 'location', $today, $term_start ),
			'latest'         => mwm_rm_latest_bookable( 'location', $today, $term_start ),
			'needs_address'  => true,
			'needs_approval' => true,
			'verb'           => 'Request',
		),
	);
}

// Validate server-side. The client-side block is convenience and never
// security — never trust the browser on a rule that costs a crew day.
//
// Returns the STATE the action lands in, which differs by mode: a studio pick
// becomes 'booked', a location pick becomes 'requested'. Nothing else may
// produce 'booked'.
function mwm_rm_validate_request( $kind, $date, $client, $today = null ) {
	$mode = mwm_rm_booking_mode( $kind );
	if ( $mode === null ) {
		return array( 'ok' => false, 'error' => 'unknown request type' );
	}
	if ( ! $date || strtotime( $date ) === false ) {
		return array( 'ok' => false, 'error' => 'pick a date' );
	}

	$term_start = isset( $client['contract_start'] ) ? $client['contract_start'] : null;
	$earliest   = mwm_rm_earliest_bookable( $kind, $today, $term_start );
	$latest     = mwm_rm_latest_bookable( $kind, $today, $term_start );

	if ( $earliest !== null && $date < $earliest ) {
		$why = ( $term_start && $date < $term_start )
			? sprintf( 'Your plan starts on %s.', $term_start )
			: sprintf( 'We need at least %s.', $kind === 'location' ? '7 days' : 'a free slot' );
		return array( 'ok' => false, 'error' => $why . ' The earliest we can take is ' . $earliest . '.',
		              'earliest' => $earliest );
	}
	if ( $latest !== null && $date > $latest ) {
		return array( 'ok' => false,
		              'error' => 'That is further ahead than we open the diary. The latest is ' . $latest . '.',
		              'latest' => $latest );
	}
	if ( mwm_rm_is_closed_day( $date ) ) {
		return array( 'ok' => false, 'error' => 'We are closed on Sundays.' );
	}

	if ( $mode === 'instant' ) {
		// 🔑 'booked' here means the RULES allow it. The caller must still hold
		// the slot against the live calendar — availability is the studio
		// portal's job and is re-checked at write time, because a free slot can
		// stop being free between rendering a page and clicking a button.
		return array( 'ok' => true, 'mode' => 'instant', 'state' => 'booked',
		              'needs_availability_check' => true );
	}

	// 🔴 A location day with no usable address is a REFUSAL, not a fallback.
	// Defaulting to the studio sends a van to Winter Park while the client
	// waits at her own office (spec §13.1).
	return array( 'ok' => true, 'mode' => 'request', 'state' => 'requested',
	              'needs_address' => true, 'needs_approval' => true );
}

// ── WHY THERE ARE NO SLOTS · never let the reason be invented ─────────────
//
// slots.py, Patch #94: "a tool that returns 'nothing' without stating why will
// have the reason invented by whatever narrates its output." That bug told
// Jaysee Soto the studio was "fully booked" on a wide-open afternoon.
//
// An empty calendar has FOUR different causes and they are not interchangeable:
//   · the feed is down          → we do not know. Say so. Never show zero.
//   · her plan has not started  → nothing is wrong; it starts on a date.
//   · her hours are spent       → she can still book, at her add-on rate.
//   · genuinely nothing free    → the only one that means "full".
//
// 🔴 Collapsing any of the first three into the fourth tells a paying client
// the studio is full when it is not. That is the same defect as August's,
// wearing a different coat.
//
// The studio portal already alerts Michael when a client is structurally
// blocked (mwm-studio-booking.php, S29) precisely because a client can
// otherwise sit in front of an empty calendar for weeks and the only way we
// find out is if she happens to email. Same posture here: the reason is
// returned, so it can be shown AND alerted on.
function mwm_rm_block_reason( $client, $hours_state = null, $today = null, $kind = 'studio' ) {
	$phase = mwm_rm_plan_phase(
		isset( $client['contract_start'] ) ? $client['contract_start'] : null,
		isset( $client['contract_end'] ) ? $client['contract_end'] : null,
		$today
	);
	if ( $phase === 'pending' ) {
		return array(
			'reason'   => 'not_started',
			'blocking' => true,
			'alert'    => false,   // expected and temporary — not worth an email
			'since'    => isset( $client['contract_start'] ) ? $client['contract_start'] : null,
		);
	}
	if ( $phase === 'ended' ) {
		return array( 'reason' => 'contract_ended', 'blocking' => true, 'alert' => true );
	}
	if ( $hours_state ) {
		$bucket = ( $kind === 'location' ) ? 'location' : 'studio';
		if ( isset( $hours_state[ $bucket ]['left'] ) && (float) $hours_state[ $bucket ]['left'] <= 0 ) {
			// 🔑 NOT blocking. Her hours are spent, but the contract lets her buy
			// more at her own rate — so the page offers that instead of an empty
			// calendar. Turning "you have used your hours" into "nothing is
			// available" loses a sale and reads as a fault.
			return array( 'reason' => 'hours_spent', 'blocking' => false, 'alert' => false,
			              'bucket' => $bucket );
		}
	}
	return null;
}

// What the page says about it, in her words. Kept beside the reasons so a new
// reason cannot be added without someone writing the sentence for it.
function mwm_rm_block_copy( $block, $client = array(), $rate_card = null ) {
	if ( ! $block ) { return null; }
	switch ( $block['reason'] ) {
		case 'not_started':
			return 'Your plan starts on ' . $block['since'] . ', so there is nothing to book yet.';
		case 'contract_ended':
			return 'Your plan has finished. Talk to us and we will pick it back up.';
		case 'hours_spent':
			$extra = '';
			if ( $rate_card ) {
				$code  = $block['bucket'] === 'location' ? 'location_hour' : 'studio_hour';
				$price = mwm_rm_price_addon( $rate_card, $code, 1, true );
				if ( $price ) {
					$extra = ' You can still book at $' . number_format( $price['unit_cents'] / 100, 0 )
					       . ' an hour, and it goes on your next invoice — no deposit,'
					       . ' and editing is included.';
				}
			}
			return 'You have used all your included hours this cycle.' . $extra;
	}
	return null;
}

// ── §5 · A LOCATION REQUEST HAS TO LAND SOMEWHERE ────────────────────────
//
// 🔴 A request button that writes nothing and tells nobody is worse than no
// button: the client believes she has asked, and nothing is true on our side.
// Spec §7.2 says it plainly — a pre-schedule "is not an FYI, it is a task with
// a deadline". Seven days of notice is not seven days of runway if the message
// sits unread for three of them.
//
// The row reuses mwm_roadmap_addons rather than inventing a second table with
// the same state machine. `code` distinguishes an included day from a paid one,
// and an INCLUDED day is priced at zero rather than left null — null means "not
// offered on this basis" everywhere else in this file, and reusing it for
// "free" would make a real refusal indistinguishable from a freebie.
function mwm_rm_shoot_request_row( $client, $date, $window, $address, $notes = '',
                                   $today = null, $miles = null ) {
	$check = mwm_rm_validate_request( 'location', $date, $client, $today );
	if ( empty( $check['ok'] ) ) { return array( 'ok' => false, 'error' => $check['error'] ); }

	// The address rule, enforced at the write site as well as the UI. A
	// location day with nowhere to go sends a van to the studio's own postcode.
	$address = trim( (string) $address );
	if ( $address === '' ) {
		return array( 'ok' => false,
		              'error' => 'We need the address before we can hold a location day.' );
	}

	$windows = array( 'morning' => 'Morning', 'afternoon' => 'Afternoon', 'full' => 'Full day' );
	$window  = isset( $windows[ $window ] ) ? $window : 'full';

	$zone = $miles === null ? null : mwm_rm_zone_for_miles( $miles );

	return array(
		'ok'  => true,
		'row' => array(
			'client_id'        => isset( $client['id'] ) ? $client['id'] : null,
			'code'             => 'included_location_day',
			'label'            => 'Location day — ' . $windows[ $window ],
			'qty'              => 1,
			'unit_cents'       => 0,          // included in the plan, not unpriced
			'total_cents'      => 0,
			'rate_card_version'=> isset( $client['rate_card_version'] ) ? $client['rate_card_version'] : '',
			'state'            => 'requested',
			'requested_by'     => isset( $client['email'] ) ? $client['email'] : '',
			'requested_at'     => $today ? $today . ' 00:00:00' : date( 'Y-m-d H:i:s' ),
			'scheduled_for'    => $date . ' 00:00:00',
			'travel_miles'     => $miles,
			'travel_zone'      => $zone ? $zone['zone'] : null,
			'travel_fee_cents' => $zone ? $zone['fee_cents'] : null,
			'notes'            => trim( (string) $notes ),
			'address'          => $address,
			'window'           => $window,
		),
	);
}

// What reaches info@. Spec §7.3: the subject carries the DECISION INPUTS, so
// Michael can triage from a phone lock screen without opening anything.
//
// 🔑 Travel is stated as unknown when it is unknown. Printing "Zone 1 —
// included" because nobody supplied a distance is how a $1,000 fee goes
// unbilled, and the honest version costs one extra line.
function mwm_rm_request_notification( $row, $client ) {
	$row  = (array) $row;
	$when = strtotime( $row['scheduled_for'] );
	$day  = $when ? date( 'D j M', $when ) : $row['scheduled_for'];
	$name = isset( $client['client_name'] ) ? $client['client_name'] : 'Client';

	$windows = array( 'morning' => 'morning', 'afternoon' => 'afternoon', 'full' => 'full day' );
	$w = isset( $windows[ $row['window'] ] ) ? $windows[ $row['window'] ] : 'full day';

	$subject = sprintf( '🎬 Requested — %s · %s, %s · ON LOCATION (%s)',
		$name, $day, $w, $row['address'] );

	if ( $row['travel_zone'] === null ) {
		$travel = 'Travel: distance not supplied, so the zone is UNKNOWN. '
		        . 'Check it before approving — Zone 4 is $1,000.';
	} elseif ( ! empty( $row['travel_fee_cents'] ) ) {
		$travel = sprintf( 'Travel: Zone %d — $%s.', $row['travel_zone'],
		                   number_format( $row['travel_fee_cents'] / 100, 0 ) );
	} else {
		$travel = sprintf( 'Travel: Zone %d — included.', $row['travel_zone'] );
	}

	$lines = array(
		$name . ' has asked for a location day. Nothing is held until you confirm.',
		'',
		'Date:     ' . ( $when ? date( 'l j F Y', $when ) : $row['scheduled_for'] ),
		'Window:   ' . ucfirst( $w ),
		'Address:  ' . $row['address'],
		$travel,
		'Hours:    comes out of her included location hours for that cycle.',
	);
	if ( ! empty( $row['notes'] ) ) {
		$lines[] = 'Notes:    ' . $row['notes'];
	}
	$lines[] = '';
	$lines[] = 'Crew check is the reason this is a request and not a booking.';
	$lines[] = 'Confirm or decline below — a decline needs a reason, and she sees it verbatim.';

	return array(
		'to'      => 'info@mwmcreations.com',
		'subject' => $subject,
		'body'    => implode( "\n", $lines ),
		'actions' => array( 'confirm', 'decline' ),
	);
}

// ── §2 · DELIVERY CEILINGS ────────────────────────────────────────────────
// 🔴 INTERNAL ONLY. Read the file header before using this anywhere near a
// client-facing string. It exists so production can plan capacity (ROB §8b)
// and so a quote can state what an add-on covers — never so a portal can
// subtract deliveries from it.
function mwm_rm_delivery_ceilings( $source, $qty = 1 ) {
	$per = array(
		'location_day' => array( 'main_videos' => 2, 'shorts' => 20 ),
		'studio_hour'  => array( 'episodes'    => 1, 'shorts' => 10 ),
	);
	if ( ! isset( $per[ $source ] ) || ! is_numeric( $qty ) || $qty < 0 ) { return null; }
	$out = array( 'internal_only' => true, 'is_ceiling' => true, 'source' => $source );
	foreach ( $per[ $source ] as $k => $v ) { $out[ $k ] = (int) round( $v * $qty ); }
	return $out;
}

// ✅ THE CLIENT-FACING ONE. Counts what exists. Takes no ceiling, so it cannot
// produce a remainder even if someone asks it to.
function mwm_rm_delivered_summary( $assets ) {
	$out = array( 'total' => 0, 'by_kind' => array() );
	foreach ( (array) $assets as $a ) {
		$a = (array) $a;
		if ( empty( $a['delivered_at'] ) ) { continue; }
		$kind = isset( $a['kind'] ) ? (string) $a['kind'] : 'other';
		$qty  = isset( $a['qty'] ) ? (int) $a['qty'] : 1;
		if ( $qty < 1 ) { $qty = 1; }
		$out['total'] += $qty;
		$out['by_kind'][ $kind ] = ( isset( $out['by_kind'][ $kind ] ) ? $out['by_kind'][ $kind ] : 0 ) + $qty;
	}
	return $out;
}

// ── §5 · BOOKING + BILLING STATE MACHINE ──────────────────────────────────
// requested → approved (written) → scheduled → delivered → billed
//
// "Nothing gets booked without written approval." The approval is the record we
// rely on if it is ever disputed, so the transition into `approved` REFUSES
// without an actor and a timestamp. A state that can be reached without
// evidence is not evidence.
function mwm_rm_addon_states() {
	return array( 'requested', 'approved', 'scheduled', 'delivered', 'billed', 'declined' );
}

function mwm_rm_addon_transition( $from, $to, $ctx = array() ) {
	$allowed = array(
		'requested' => array( 'approved', 'declined' ),
		'approved'  => array( 'scheduled', 'declined' ),
		'scheduled' => array( 'delivered', 'declined' ),
		'delivered' => array( 'billed' ),
		'billed'    => array(),
		'declined'  => array(),
	);
	if ( ! isset( $allowed[ $from ] ) ) {
		return array( 'ok' => false, 'error' => 'unknown state: ' . $from );
	}
	if ( ! in_array( $to, $allowed[ $from ], true ) ) {
		return array( 'ok' => false, 'error' => sprintf( '%s cannot become %s', $from, $to ) );
	}
	// 🔴 The written-approval rule, enforced rather than documented.
	if ( $to === 'approved' ) {
		if ( empty( $ctx['approved_by'] ) || empty( $ctx['approved_at'] ) ) {
			return array( 'ok' => false, 'error' => 'written approval requires approved_by and approved_at' );
		}
	}
	if ( $to === 'declined' && empty( $ctx['reason'] ) ) {
		return array( 'ok' => false, 'error' => 'a decline must carry a reason' );
	}
	return array( 'ok' => true, 'state' => $to );
}

// Add-ons bill on the NEXT invoice, together with the subscription — never a
// separate charge, never a deposit. This returns the cycle an approved add-on
// lands on, so the answer is computed in one place.
function mwm_rm_billing_cycle_for( $approved_on, $anchor_day ) {
	$cycle = mwm_rm_cycle_window( $anchor_day, $approved_on );
	if ( ! $cycle ) { return null; }
	return array(
		'used_within'  => $cycle,                 // approved hours are used THIS cycle
		'invoiced_on'  => $cycle['next_start'],   // and billed on the NEXT invoice
		'separate_charge' => false,
		'deposit'      => false,
	);
}

// ── §6 · TERMS THE PORTAL HAS TO STATE ────────────────────────────────────
// Published on the page in plain words, BEFORE the client does the thing.
function mwm_rm_terms( $version = '2026-09' ) {
	return array(
		'rate_card'          => $version,
		'delivery_days'      => '7 to 9 business days after filming is completed',
		'revision_rounds'    => 3,
		'revision_window_days' => 30,
		'extra_revision_cents' => 25000,
		'revision_turnaround'  => 'up to 3 business days',
		'cancel_notice_hours'  => 72,
		'cancel_late_rule'     => 'A filming day cancelled inside 72 hours counts as used.',
		'raw_footage_cents_per_minute' => 2500,
		'raw_footage_rule'   => 'By written request, paid in full before release.',
		'renewal'            => 'Automatic, unless cancelled at least 30 days before the renewal date.',
		'early_termination'  => 'A fee equal to two months of the current plan.',
		'availability_rule'  => 'Everything is subject to studio and crew availability.',
	);
}

// ── ROB §8a · INTERNAL UPGRADE SIGNAL ─────────────────────────────────────
// Platinum $4,397 − Gold $2,497 = $1,900. At $249/h that is 7.6 studio hours,
// so from ~8 extra studio hours in a cycle the add-ons undercut our own ladder.
// 🔴 Staff-side only. Never rendered to the client.
function mwm_rm_upgrade_signal( $extra_studio_hours, $version = '2026-09' ) {
	$price = mwm_rm_price_addon( $version, 'studio_hour', 1, true );
	if ( ! $price ) { return null; }
	$gap_cents = 439700 - 249700;
	$threshold = $gap_cents / $price['unit_cents'];   // 7.63
	return array(
		'internal_only' => true,
		'hours'         => (float) $extra_studio_hours,
		'threshold'     => round( $threshold, 2 ),
		'flag'          => (float) $extra_studio_hours >= 8.0,
		'why'           => 'At or above this, buying add-on hours costs the client less than upgrading to Platinum.',
	);
}

} // MWM_RM_ENTITLEMENT
