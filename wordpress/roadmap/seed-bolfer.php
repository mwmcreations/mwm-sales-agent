<?php
// Code Snippets plugin — MWM ROADMAP™ · SEED: Dr. Luiz Bolfer
// DEV · Aug 11 2026 · seed v2 · key "bolfer"
//
// GENERATED from docs/roadmap-seed/bolfer_data.json by tools/gen_seed.py.
// DO NOT HAND-EDIT — change the JSON and regenerate.
//
// 🔴 IDEMPOTENT and SCOPED TO ONE CLIENT. Guarded by mwm_roadmap_seed_bolfer. Bump the
// version to re-seed; that path deletes THIS client's campaigns, assets and actions
// and rebuilds them. Every statement is filtered by this client's id — no other
// client is read, updated or deleted.
//
// 🔴 The access code is generated here, stored hashed, and the plaintext is parked in
// mwm_roadmap_seed_code_once for the bootstrap snippet to mail to Michael and delete.
// It is never logged and never returned to an agent.

if ( ! defined( 'ABSPATH' ) ) { exit; }

define( 'MWM_RM_SEED_BOLFER_VERSION', '2' );

function mwm_rm_seed_bolfer() {

	global $wpdb;
	$p = $wpdb->prefix;
	$clients   = $p . 'mwm_roadmap_clients';
	$campaigns = $p . 'mwm_roadmap_campaigns';
	$assets    = $p . 'mwm_roadmap_assets';
	$actions   = $p . 'mwm_roadmap_actions';

	if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $clients ) ) !== $clients ) {
		error_log( '[MWM ROADMAP seed bolfer] aborted — schema missing. Is the schema snippet active?' );
		return;
	}

	$email     = 'drbolfer@gmail.com';
	$client_id = (int) $wpdb->get_var( $wpdb->prepare( "SELECT id FROM {$clients} WHERE email = %s", $email ) );

	if ( ! $client_id ) {
		// Same alphabet as the studio portal — no ambiguous characters, because a
		// client reads this off an email and types it on a phone.
		$chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
		$code  = '';
		for ( $i = 0; $i < 6; $i++ ) { $code .= $chars[ wp_rand( 0, strlen( $chars ) - 1 ) ]; }

		$wpdb->insert( $clients, array(
			'client_name'          => 'Dr. Luiz Bolfer',
			'company'              => '',
			'email'                => $email,
			'access_code'          => wp_hash_password( $code ),
			'plan'                 => 'gold',
			'campaigns_allowed'    => 12,
			'captures_allowed'     => 4,
			'studio_hours_allowed' => 12,
			'conversions_used'     => 0,
			'contract_start'       => '2026-06-10',
			'contract_end'         => '2027-06-09',
			'strategist'           => 'Michael Moraes',
			'language'             => 'en',
			'status'               => 'active',
			'studio_client_id'     => null,
		) );
		$client_id = (int) $wpdb->insert_id;
		update_option( 'mwm_roadmap_seed_code_once', $code, false );
	}

	if ( ! $client_id ) {
		error_log( '[MWM ROADMAP seed bolfer] aborted — no client row.' );
		return;
	}

	// Keep the plan facts current without ever touching the access code.
	$wpdb->update( $clients, array(
		'campaigns_allowed'    => 12,
		'captures_allowed'     => 4,
		'studio_hours_allowed' => 12,
		'studio_client_id'     => null,
		'contract_start'       => '2026-06-10',
		'contract_end'         => '2027-06-09',
	), array( 'id' => $client_id ) );

	// 🔴 Rebuild ONLY the rows we author. A shoot the client has already requested
	// lives on the campaign row, so re-seeding would silently throw it away —
	// therefore campaigns are only wiped when none of them has been touched.
	$touched = (int) $wpdb->get_var( $wpdb->prepare(
		"SELECT COUNT(*) FROM {$campaigns} WHERE client_id = %d AND shoot_state <> 'none'", $client_id ) );

	if ( $touched > 0 ) {
		error_log( '[MWM ROADMAP seed bolfer] skipped campaign rebuild — client has live bookings.' );
		update_option( 'mwm_roadmap_seed_bolfer', MWM_RM_SEED_BOLFER_VERSION, false );
		return;
	}

	$old = $wpdb->get_col( $wpdb->prepare( "SELECT id FROM {$campaigns} WHERE client_id = %d", $client_id ) );
	if ( $old ) {
		$in = implode( ',', array_map( 'intval', $old ) );
		$wpdb->query( "DELETE FROM {$assets} WHERE campaign_id IN ({$in})" );
		$wpdb->query( $wpdb->prepare( "DELETE FROM {$campaigns} WHERE client_id = %d", $client_id ) );
	}
	$wpdb->query( $wpdb->prepare( "DELETE FROM {$actions} WHERE client_id = %d", $client_id ) );


	// ── campaign 1 · The Educational Library ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 1,
		'title'          => 'The Educational Library',
		'theme_desc'     => 'The five or six conditions you see most, starting with mitral valve disease. Ten to fifteen minutes each, filmed with a teleprompter in your own room, and the heart animations from your iPad cut in full-screen while you explain. The point is that a patient arrives already knowing what they have, so the appointment starts at the question instead of the explanation.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => 'location',
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 1,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── campaign 2 · The Surgery, Explained ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 2,
		'title'          => 'The Surgery, Explained',
		'theme_desc'     => 'The operation you perform, told so that a patient understands it before they consent to it — what happens, why, and what it is like afterwards. Longer than the others, and filmed where the work actually happens.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => 'location',
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 2,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── campaign 3 · Coming In For Surgery ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 3,
		'title'          => 'Coming In For Surgery',
		'theme_desc'     => 'What the day is actually like, from arriving to going home. The film that answers the questions nobody has time to ask in a consultation, and takes the fear out of the part patients imagine worst.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => 'location',
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 3,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── campaign 4 · The Process, Updated ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 4,
		'title'          => 'The Process, Updated',
		'theme_desc'     => 'Your words: the existing film no longer matches how you work. A re-make rather than a repair, filmed alongside the two campaigns above so it costs you no extra time.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => 'location',
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 4,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── campaign 5 · Meet Dr. Bolfer ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 5,
		'title'          => 'Meet Dr. Bolfer',
		'theme_desc'     => 'Who you are and why you practise the way you do. Deliberately not first — by the time this exists, your patients have already watched you explain their own condition, so the film about you lands on people who have decided they trust you.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => 'location',
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 5,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── campaign 6 · A Patient's Story ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 6,
		'title'          => 'A Patient\'s Story',
		'theme_desc'     => 'One person: their condition, their operation, their life afterwards. The most persuasive thing a cardiologist can publish, and the only one you cannot make on your own.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => 'location',
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 6,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── campaign 7 · Ask the Cardiologist ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 7,
		'title'          => 'Ask the Cardiologist',
		'theme_desc'     => 'Short, direct answers to the questions you are asked in almost every appointment. A lot of finished pieces from a single sitting, and they feed the library you are already building.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => 'location',
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 7,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── campaign 8 · Myths About Your Heart ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 8,
		'title'          => 'Myths About Your Heart',
		'theme_desc'     => 'The things patients arrive already believing that are simply wrong. Corrective, easy to share, and it reaches further than anything else in the plan.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => 'location',
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 8,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── campaign 9 · A Second Story ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 9,
		'title'          => 'A Second Story',
		'theme_desc'     => 'A different patient and a different route in — someone who came through a referral, or who waited longer than they should have. One story is an anecdote; two is a pattern.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => 'location',
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 9,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── campaign 10 · Referring Physicians ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 10,
		'title'          => 'Referring Physicians',
		'theme_desc'     => 'Films made with the doctors who send you patients. Your growth comes through them, and their audience meets you in their words rather than in your own.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => 'location',
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 10,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── campaign 11 · The Library, Part Two ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 11,
		'title'          => 'The Library, Part Two',
		'theme_desc'     => 'The next set of conditions, once the first library has been out in the world long enough to show which explanations patients actually watch to the end.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => 'location',
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 11,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── campaign 12 · The Year, Told Back ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 12,
		'title'          => 'The Year, Told Back',
		'theme_desc'     => 'The library you built, the patients it reached, and what you want to say next.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => 'location',
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 12,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── needs your attention ──
	$wpdb->insert( $actions, array(
		'client_id' => $client_id,
		'title'     => 'Pick your first filming day',
		'detail'    => 'We come to your office — you do not need to travel or give up a weekend. Choose a day above and we will confirm it with you. On location we need seven days\' notice so the crew and kit can be booked.',
		'due_date'  => null,
		'resolved'  => 0,
	) );
	$wpdb->insert( $actions, array(
		'client_id' => $client_id,
		'title'     => 'Send us the reference videos you liked',
		'detail'    => 'On our call you mentioned some examples on YouTube you wanted the style to be close to. Send them whenever you have a moment — they shape how we shoot the first day.',
		'due_date'  => null,
		'resolved'  => 0,
	) );
	$wpdb->insert( $actions, array(
		'client_id' => $client_id,
		'title'     => 'Bring your scripts, and tell us which conditions come first',
		'detail'    => 'You said you would write them so the videos stay tight. The teleprompter will be set up and ready. Tell us which two or three conditions you want to start with and we will build the day around them.',
		'due_date'  => null,
		'resolved'  => 0,
	) );

	update_option( 'mwm_roadmap_seed_bolfer', MWM_RM_SEED_BOLFER_VERSION, false );
}

add_action( 'init', function () {
	if ( get_option( 'mwm_roadmap_seed_bolfer' ) !== MWM_RM_SEED_BOLFER_VERSION ) {
		mwm_rm_seed_bolfer();
	}
}, 5 );
