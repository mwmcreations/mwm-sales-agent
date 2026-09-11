<?php
// MWM ROADMAP™ Portal · GOLD PANEL (render)
// DEV · Sep 11 2026 · v1.0.0 · pairs with entitlement.php v1.0.0
//
// Renders the contract-backed half of the portal for a GOLD ROADMAP client.
// Pure: takes arrays, returns a string. No $wpdb, no globals, so the offline
// harness and the live page render from identical code.
//
// ══════════════════════════════════════════════════════════════════════════
// 🔴 WHAT THIS FILE IS NOT ALLOWED TO SAY
// ROB, Sep 11: "THE PORTAL MUST NEVER RENDER THESE AS A BALANCE OWED. No '18
// of 20 shorts remaining', no '2 videos still to be delivered', no progress bar
// that empties toward a debt... a client will hold us to the screen, not the PDF."
//
// So the delivered section is a LIST OF WHAT EXISTS. It is built from the asset
// rows alone; no ceiling is in scope in this function, and test_gold_panel.py
// greps the rendered HTML for the forbidden shapes on every run.
//
// Hours are the deliberate exception, and the reason is not a loophole: hours
// are a contracted allowance that EXPIRES (§1, não cumulativas). Telling Luzia
// she has 2.5 hours left and a date they die is information she is owed —
// saying nothing is what makes them expire unused. A delivery ceiling is the
// opposite: a cap on our obligation, which becomes a promise the moment it is
// rendered as a remainder.
// ══════════════════════════════════════════════════════════════════════════

if ( ! function_exists( 'esc_html' ) ) {
	function esc_html( $v ) { return htmlspecialchars( (string) $v, ENT_QUOTES, 'UTF-8' ); }
}
if ( ! function_exists( 'esc_attr' ) ) {
	function esc_attr( $v ) { return htmlspecialchars( (string) $v, ENT_QUOTES, 'UTF-8' ); }
}

function mwm_rm_money( $cents ) {
	if ( $cents === null ) { return 'On request'; }
	return '$' . number_format( $cents / 100, ( $cents % 100 === 0 ) ? 0 : 2 );
}

function mwm_rm_hrs( $h ) {
	$h = (float) $h;
	return ( floor( $h ) == $h ) ? (string) (int) $h : rtrim( rtrim( number_format( $h, 2 ), '0' ), '.' );
}

function mwm_rm_date_long( $ymd ) {
	$ts = $ymd ? strtotime( $ymd ) : false;
	return $ts ? date( 'j F Y', $ts ) : '';
}

// ── the hours meter ───────────────────────────────────────────────────────
// Shows used AND left, because both are true of an allowance. The bar fills as
// she uses her time; it is not a countdown toward an obligation on our side.
function mwm_rm_hour_meter( $label, $state, $note = '' ) {
	$inc  = (float) $state['included'];
	$used = (float) $state['used'];
	$left = (float) $state['left'];
	$pct  = $inc > 0 ? min( 100, round( ( $used / $inc ) * 100 ) ) : 0;

	$h  = '<div class="rm-meter" data-kind="hours">';
	$h .= '<div class="rm-meter-head"><span class="rm-meter-label">' . esc_html( $label ) . '</span>';
	$h .= '<span class="rm-meter-figure">' . esc_html( mwm_rm_hrs( $left ) ) . ' h left</span></div>';
	$h .= '<div class="rm-bar"><span style="width:' . (int) $pct . '%"></span></div>';
	$h .= '<p class="rm-meter-sub">' . esc_html( mwm_rm_hrs( $used ) ) . ' of your '
	    . esc_html( mwm_rm_hrs( $inc ) ) . ' hours used this cycle.</p>';
	if ( $note ) { $h .= '<p class="rm-meter-note">' . esc_html( $note ) . '</p>'; }
	return $h . '</div>';
}

// ── §1 · this cycle ───────────────────────────────────────────────────────
function mwm_rm_cycle_panel( $client, $hours_state ) {
	$h = '<section class="rm-card rm-cycle"><h2>This cycle</h2>';

	// 🔴 The anchor is unknown when the contract was signed without a start
	// date. Guessing one would expire her hours on the wrong day and nothing on
	// screen would say so. An honest gap beats a confident wrong number.
	if ( ! $hours_state ) {
		$h .= '<p class="rm-pending">Your billing cycle starts on the date your'
		    . ' subscription begins, and we are confirming that with you now.'
		    . ' As soon as it is set, this is where you will see the hours you'
		    . ' have this cycle and the date they run to.</p>';
		$h .= '<p class="rm-meter-note">Your plan includes up to 4 hours on'
		    . ' location and up to 4 hours in the studio every cycle.</p>';
		return $h . '</section>';
	}

	$h .= '<p class="rm-cycle-window">' . esc_html( mwm_rm_date_long( $hours_state['cycle_start'] ) )
	    . ' to ' . esc_html( mwm_rm_date_long( $hours_state['cycle_end'] ) ) . '</p>';
	$h .= mwm_rm_hour_meter( 'On location', $hours_state['location'] );
	$h .= mwm_rm_hour_meter( 'In the studio', $hours_state['studio'] );
	$h .= '<p class="rm-expiry">🔴 These hours are for this cycle only — they do'
	    . ' not carry over. Anything unused ends on '
	    . esc_html( mwm_rm_date_long( $hours_state['expires_on'] ) ) . '.</p>';
	$h .= '<p class="rm-meter-note">Recording time starts when the crew arrives.'
	    . ' Travel never comes out of your hours.</p>';
	return $h . '</section>';
}

// ── §2 · delivered · 🔴 A LIST OF WHAT EXISTS, AND NOTHING ELSE ──────────
// No $ceiling parameter. There is nothing here to subtract from.
function mwm_rm_delivered_panel( $assets ) {
	$summary = mwm_rm_delivered_summary( $assets );
	$h = '<section class="rm-card rm-delivered"><h2>Delivered to you</h2>';

	if ( $summary['total'] === 0 ) {
		$h .= '<p class="rm-empty">Nothing has been delivered yet. Everything we'
		    . ' finish will appear here, ready to watch and download.</p>';
		return $h . '</section>';
	}

	$h .= '<p class="rm-delivered-count">' . (int) $summary['total'] . ' '
	    . ( $summary['total'] === 1 ? 'film' : 'films' ) . ' delivered so far.</p>';
	$h .= '<ul class="rm-asset-list">';
	foreach ( (array) $assets as $a ) {
		$a = (array) $a;
		if ( empty( $a['delivered_at'] ) ) { continue; }
		$h .= '<li class="rm-asset"><span class="rm-asset-title">'
		    . esc_html( isset( $a['title'] ) ? $a['title'] : 'Untitled' ) . '</span>';
		if ( ! empty( $a['kind'] ) ) {
			$h .= ' <span class="rm-asset-kind">' . esc_html( $a['kind'] ) . '</span>';
		}
		$h .= ' <span class="rm-asset-date">' . esc_html( mwm_rm_date_long( $a['delivered_at'] ) ) . '</span>';
		if ( ! empty( $a['url'] ) ) {
			$h .= ' <a class="rm-asset-link" href="' . esc_attr( $a['url'] ) . '">Open</a>';
		}
		$h .= '</li>';
	}
	return $h . '</ul></section>';
}

// ── the roadmap · honest when it does not exist yet ──────────────────────
// Spec §11.2: never render a client's own year as empty boxes with padlocks.
// Twelve blank months is not aspiration, it is twelve reminders that nothing
// has happened — inside a product she already pays for.
function mwm_rm_roadmap_panel( $campaigns ) {
	$h = '<section class="rm-card rm-roadmap"><h2>Your year</h2>';
	if ( empty( $campaigns ) ) {
		$h .= '<p class="rm-pending">Michael is building your annual roadmap now'
		    . ' — the themes, the shape of each campaign, and what we film when.'
		    . ' The whole year will appear here in one view as soon as it is'
		    . ' ready.</p>';
		return $h . '</section>';
	}
	$h .= '<ol class="rm-campaigns">';
	foreach ( $campaigns as $c ) {
		$c = (array) $c;
		$h .= '<li class="rm-campaign" data-status="' . esc_attr( $c['status'] ) . '">'
		    . '<span class="rm-campaign-title">Campaign ' . (int) $c['month_no'] . ' · '
		    . esc_html( $c['title'] ) . '</span></li>';
	}
	return $h . '</ol></section>';
}

// ── §5 · what you can ask for, priced from HER rate card ─────────────────
// Spec §10.8.3: what creates an extra cost is published on the page, in plain
// words, BEFORE the client does it. Prices come from the version stamped on her
// subscription (ToS §13), never from whatever is current.
function mwm_rm_addon_menu_panel( $rate_card_version, $on_annual = true ) {
	$card = mwm_rm_rate_card( $rate_card_version );
	if ( ! $card ) { return ''; }

	$h  = '<section class="rm-card rm-addons"><h2>If you need more than the plan includes</h2>';
	$h .= '<p class="rm-lede">These are your prices, held at the rates in your'
	    . ' agreement. Nothing is booked until you approve it in writing, and'
	    . ' everything is subject to studio and crew availability.</p>';
	$h .= '<table class="rm-rate-table"><tbody>';
	foreach ( $card['items'] as $code => $item ) {
		$p = mwm_rm_price_addon( $card['version'], $code, 1, $on_annual );
		if ( ! $p ) { continue; }
		$price = $p['waived'] ? 'Included' : mwm_rm_money( $p['unit_cents'] );
		if ( ! $p['waived'] && $item['unit'] === 'hour' ) { $price .= ' / hour'; }
		$h .= '<tr><th>' . esc_html( $item['label'] ) . '</th>'
		    . '<td class="rm-price">' . esc_html( $price ) . '</td></tr>';
		if ( ! empty( $item['note'] ) ) {
			$h .= '<tr class="rm-rate-note"><td colspan="2">' . esc_html( $item['note'] ) . '</td></tr>';
		}
	}
	$h .= '</tbody></table>';
	$h .= '<p class="rm-meter-note">Quoted separately: '
	    . esc_html( strtolower( implode( ', ', $card['quote_only'] ) ) ) . '.</p>';
	$h .= '<p class="rm-meter-note">Anything you approve goes on your next'
	    . ' invoice together with the subscription. No deposit, and never a'
	    . ' separate charge. Approved hours are used within the same cycle.</p>';
	return $h . '</section>';
}

// ── §3 · travel, so the number is known before the date is picked ────────
function mwm_rm_travel_panel( $version = 'v1.1' ) {
	$t = mwm_rm_travel_zones( $version );
	$h  = '<section class="rm-card rm-travel"><h2>Filming outside Orlando</h2>';
	$h .= '<p class="rm-lede">Anywhere inside Greater Orlando, there is no travel'
	    . ' cost. Beyond it we use one fixed table, measured by driving route from'
	    . ' the studio. It is the same table for every client, and you will always'
	    . ' know the figure before you book.</p><table class="rm-rate-table"><tbody>';
	foreach ( $t['zones'] as $z ) {
		$fee = $z['included'] ? 'Included'
			: ( ! empty( $z['quote_only'] ) ? 'On request' : mwm_rm_money( $z['fee_cents'] ) );
		$h .= '<tr><th>Zone ' . (int) $z['zone'] . ' · ' . esc_html( $z['label'] ) . '</th>'
		    . '<td class="rm-price">' . esc_html( $fee ) . '</td></tr>';
	}
	$h .= '</tbody></table><p class="rm-meter-note">The fee covers the vehicle,'
	    . ' fuel, equipment transport and coordination. It does not include '
	    . esc_html( implode( ', ', $t['excludes'] ) ) . ', which are billed at cost'
	    . ' when they apply. In every zone, recording time starts on arrival.</p>';
	return $h . '</section>';
}

// ── §5 · open requests · the state machine, in her words ─────────────────
function mwm_rm_requests_panel( $addons ) {
	if ( empty( $addons ) ) { return ''; }
	$words = array(
		'requested' => 'Waiting for your go-ahead',
		'approved'  => 'Approved — we are scheduling it',
		'scheduled' => 'Booked',
		'delivered' => 'Filmed and delivered',
		'billed'    => 'On your invoice',
		'declined'  => 'Not going ahead',
	);
	$h = '<section class="rm-card rm-requests"><h2>Open requests</h2>';
	foreach ( $addons as $a ) {
		$a = (array) $a;
		$state = isset( $a['state'] ) ? $a['state'] : 'requested';
		$h .= '<article class="rm-request" data-state="' . esc_attr( $state ) . '">';
		$h .= '<h3>' . esc_html( $a['label'] ) . '</h3>';
		$h .= '<p class="rm-request-state">' . esc_html( isset( $words[ $state ] ) ? $words[ $state ] : $state ) . '</p>';
		if ( ! empty( $a['proposed_for'] ) ) {
			$h .= '<p class="rm-request-date">Held for ' . esc_html( mwm_rm_date_long( $a['proposed_for'] ) ) . '</p>';
		}
		if ( isset( $a['quoted_total_cents'] ) ) {
			$h .= '<p class="rm-request-total">' . esc_html( mwm_rm_money( $a['quoted_total_cents'] ) );
			if ( ! empty( $a['travel_fee_cents'] ) ) {
				$h .= ' <span class="rm-request-breakdown">including '
				    . esc_html( mwm_rm_money( $a['travel_fee_cents'] ) )
				    . ' travel, zone ' . (int) $a['travel_zone'] . '</span>';
			}
			$h .= '</p>';
		}
		// 🔴 The sentence that keeps a held date from reading as a booked one.
		if ( $state === 'requested' ) {
			$h .= '<p class="rm-request-caveat">We are holding this date, but'
			    . ' nothing is booked until you confirm in writing.</p>';
		}
		$h .= '</article>';
	}
	return $h . '</section>';
}

// ── §6 · the terms, in plain words ───────────────────────────────────────
function mwm_rm_terms_panel( $version = '2026-09' ) {
	$t = mwm_rm_terms( $version );
	$rows = array(
		'Delivery'            => ucfirst( $t['delivery_days'] ) . '.',
		'Adjustments'         => $t['revision_rounds'] . ' rounds per campaign, within '
		                         . $t['revision_window_days'] . ' days of delivery. Further rounds are '
		                         . mwm_rm_money( $t['extra_revision_cents'] ) . ' each, turned around in '
		                         . $t['revision_turnaround'] . '.',
		'Moving a filming day'=> 'Written notice at least ' . $t['cancel_notice_hours']
		                         . ' hours ahead. ' . $t['cancel_late_rule'],
		'Raw footage'         => mwm_rm_money( $t['raw_footage_cents_per_minute'] ) . ' per minute. ' . $t['raw_footage_rule'],
		'Renewal'             => $t['renewal'],
		'Ending early'        => $t['early_termination'],
	);
	$h = '<section class="rm-card rm-terms"><h2>Good to know</h2><dl class="rm-terms-list">';
	foreach ( $rows as $k => $v ) {
		$h .= '<dt>' . esc_html( $k ) . '</dt><dd>' . esc_html( $v ) . '</dd>';
	}
	return $h . '</dl></section>';
}

// ── the whole panel ──────────────────────────────────────────────────────
function mwm_rm_gold_panel( $data, $hours_state = null, $assets = array() ) {
	$c    = (array) $data['client'];
	$copy = isset( $data['plan_copy'] ) ? (array) $data['plan_copy'] : array();

	$h  = '<div class="rm-portal rm-gold">';
	$h .= '<header class="rm-header"><p class="rm-client">' . esc_html( $c['client_name'] ) . '</p>';
	$h .= '<h1>' . esc_html( isset( $copy['headline'] ) ? $copy['headline'] : 'GOLD ROADMAP' ) . '</h1>';
	if ( ! empty( $copy['price_line'] ) ) {
		$h .= '<p class="rm-plan-line">' . esc_html( $copy['price_line'] ) . '</p>';
	}
	$h .= '</header>';

	$h .= '<section class="rm-card rm-included"><h2>What your plan includes, every cycle</h2><ul>';
	foreach ( (array) ( isset( $copy['included_lines'] ) ? $copy['included_lines'] : array() ) as $line ) {
		$h .= '<li>' . esc_html( $line ) . '</li>';
	}
	$h .= '</ul>';
	if ( ! empty( $copy['hours_note'] ) ) {
		$h .= '<p class="rm-meter-note">' . esc_html( $copy['hours_note'] ) . '</p>';
	}
	$h .= '</section>';

	$h .= mwm_rm_cycle_panel( $c, $hours_state );
	$h .= mwm_rm_delivered_panel( $assets );
	$h .= mwm_rm_roadmap_panel( isset( $data['campaigns'] ) ? $data['campaigns'] : array() );
	$h .= mwm_rm_requests_panel( isset( $data['addons'] ) ? $data['addons'] : array() );
	$h .= mwm_rm_addon_menu_panel( $c['rate_card_version'], true );
	$h .= mwm_rm_travel_panel( $c['travel_policy_version'] );
	$h .= mwm_rm_terms_panel( $c['rate_card_version'] );

	return $h . '</div>';
}
