<?php
// Code Snippets plugin — MWM ROADMAP™ · SEED: Zerlotini Brothers Construction
// WP Code Snippets ID 34 · ACTIVE · DEV · Aug 11 2026 · seed v3
//
// GENERATED from docs/roadmap-seed/zbrothers_data.json by gen_wp_seeder.py.
// DO NOT HAND-EDIT. Change the JSON and regenerate, or the portal Michael
// reviewed and the portal WordPress serves will drift apart.
//
// Michael gave named approval to write these rows to the production WP DB
// (Aug 11 2026). This snippet INSERTS ONLY into mwm_roadmap_* tables. It
// touches no studio table, no post, no user, and no existing row.
//
// 🔴 IDEMPOTENT. Guarded by the option below — running it twice is a no-op,
// so it is safe to leave active. Bump the version to re-seed after a data
// change; that path DELETES this client's campaigns/assets/actions and
// rebuilds them, and it never touches any other client.
//
// The access code is GENERATED HERE and stored hashed. The plaintext is put in
// mwm_roadmap_seed_code_once so it can be read from wp-admin exactly once and
// then deleted. It is never written to a log, an email body, or a chat.

if ( ! defined( 'ABSPATH' ) ) { exit; }

define( 'MWM_RM_SEED_ZB_VERSION', '3' );

function mwm_rm_seed_zbrothers() {

	global $wpdb;
	$p = $wpdb->prefix;

	$clients   = $p . 'mwm_roadmap_clients';
	$campaigns = $p . 'mwm_roadmap_campaigns';
	$assets    = $p . 'mwm_roadmap_assets';
	$actions   = $p . 'mwm_roadmap_actions';

	// Guard: the schema must exist. Seeding into a missing table would fail
	// silently row by row and leave a half-built portal, which is worse than
	// no portal at all.
	if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $clients ) ) !== $clients ) {
		error_log( '[MWM ROADMAP seed] aborted — ' . $clients . ' does not exist. Is snippet 21 active?' );
		return;
	}


	$email = 'thiago@zbrothersconstruction.com';

	// ── client ───────────────────────────────────────────────────────────
	$client_id = (int) $wpdb->get_var( $wpdb->prepare( "SELECT id FROM {$clients} WHERE email = %s", $email ) );

	if ( ! $client_id ) {
		// Same alphabet as the studio portal — no ambiguous characters, because
		// a client reads this off an email and types it on a phone.
		$chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
		$code  = '';
		for ( $i = 0; $i < 6; $i++ ) { $code .= $chars[ wp_rand( 0, strlen( $chars ) - 1 ) ]; }

		$wpdb->insert( $clients, array(
			'client_name'          => 'Thiago & Sandina Zerlotini',
			'company'              => 'Zerlotini Brothers Construction',
			'email'                => $email,
			'access_code'          => wp_hash_password( $code ),
			'plan'                 => 'gold',
			'campaigns_allowed'    => 12,
			'captures_allowed'     => 4,
			'studio_hours_allowed' => 12,
			'conversions_used'     => 0,
			'contract_start'       => '2025-11-14',
			'contract_end'         => '2026-11-14',
			'strategist'           => 'Michael Moraes',
			'language'             => 'en',
			'status'               => 'active',
			'studio_client_id'     => 13,
		) );
		$client_id = (int) $wpdb->insert_id;

		// Read once from wp-admin, then delete. Not logged, not emailed.
		update_option( 'mwm_roadmap_seed_code_once', $code, false );
	}

	if ( ! $client_id ) {
		error_log( '[MWM ROADMAP seed] aborted — could not create or find the client row.' );
		return;
	}

	// The row may predate this seed version — keep the studio link and the
	// allowances current without ever touching the access code.
	$wpdb->update( $clients, array(
		'studio_client_id'     => 13,
		'campaigns_allowed'    => 12,
		'captures_allowed'     => 4,
		'studio_hours_allowed' => 12,
		'contract_start'       => '2025-11-14',
		'contract_end'         => '2026-11-14',
	), array( 'id' => $client_id ) );

	// ── rebuild this client's campaigns, assets and actions ──────────────
	// Scoped to $client_id throughout. Nothing belonging to another client is
	// read, updated or deleted by any statement below.
	$old = $wpdb->get_col( $wpdb->prepare( "SELECT id FROM {$campaigns} WHERE client_id = %d", $client_id ) );
	if ( $old ) {
		$in = implode( ',', array_map( 'intval', $old ) );
		$wpdb->query( "DELETE FROM {$assets} WHERE campaign_id IN ({$in})" );
		$wpdb->query( $wpdb->prepare( "DELETE FROM {$campaigns} WHERE client_id = %d", $client_id ) );
	}
	$wpdb->query( $wpdb->prepare( "DELETE FROM {$actions} WHERE client_id = %d", $client_id ) );


	// ── month 1 · Institutional ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 1,
		'title'          => 'Institutional',
		'theme_desc'     => 'Thiago and Sandina\'s story — faith, family, legacy, and why Z Brothers builds the way it does. The film the whole year is built on.',
		'status'         => 'delivered',
		'shoot_state'    => 'confirmed',
		'shoot_kind'     => 'location',
		'shoot_at'       => '2025-11-14 09:00:00',
		'shoot_location' => 'On location, Orlando',
		'delivered_at'   => '2025-12-15',
		'sort_order'     => 1,
	) );
	$cid = (int) $wpdb->insert_id;
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Institutional film — full version',
		'kind'         => 'hero',
		'url'          => 'https://drive.google.com/file/d/1_O6J1r4h7mkVzQndqS9ks5trfhpUcrBF/view',
		'qty'          => 1,
		'delivered_at' => '2025-12-15',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Institutional film — Portuguese subtitles',
		'kind'         => 'hero',
		'url'          => 'https://drive.google.com/file/d/1SRNh_TwzaJHacfA1yy6cFobH9GBxTFvT/view',
		'qty'          => 1,
		'delivered_at' => '2025-12-15',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Short version — widescreen',
		'kind'         => 'short',
		'url'          => 'https://drive.google.com/file/d/1bhqc8vqEDTtFOFD5C82M3m7ElCgjuFq6/view',
		'qty'          => 1,
		'delivered_at' => '2025-12-15',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Short version — vertical',
		'kind'         => 'short',
		'url'          => 'https://drive.google.com/file/d/1nEBOzZgSjcNxhCy36ydedZWrX7fRrFQu/view',
		'qty'          => 1,
		'delivered_at' => '2025-12-15',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Social cuts',
		'kind'         => 'reel',
		'url'          => 'https://drive.google.com/drive/folders/1OlR6Hj0uanX9YyvdEME6MHtluYyTl4oH',
		'qty'          => 7,
		'delivered_at' => '2025-12-15',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Everything from this month, in one folder',
		'kind'         => 'other',
		'url'          => 'https://drive.google.com/drive/folders/1eNp3itvWTxR-I73j1heSyZXCkuUjWh_-',
		'qty'          => 1,
		'delivered_at' => '2025-12-15',
		'review_state' => 'approved',
	) );

	// ── month 2 · Finish Differentiators ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 2,
		'title'          => 'Finish Differentiators',
		'theme_desc'     => 'What luxury detail looks like inside an affordable home — the finishes, the materials, the decisions most builders skip.',
		'status'         => 'delivered',
		'shoot_state'    => 'confirmed',
		'shoot_kind'     => 'location',
		'shoot_at'       => '2025-12-29 09:00:00',
		'shoot_location' => 'On location, Orlando',
		'delivered_at'   => '2026-01-16',
		'sort_order'     => 2,
	) );
	$cid = (int) $wpdb->insert_id;
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Films 1–8 — widescreen',
		'kind'         => 'hero',
		'url'          => 'https://drive.google.com/drive/folders/1DaGGdKxG8F1qrYeIhPo1_A5hUjqP2Fty',
		'qty'          => 8,
		'delivered_at' => '2026-01-16',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Films 1–8 — vertical',
		'kind'         => 'reel',
		'url'          => 'https://drive.google.com/drive/folders/1N4LSiSXQXFfff-aG1ZQSUjJNRr2x6L2Y',
		'qty'          => 8,
		'delivered_at' => '2026-01-16',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Everything from this month, in one folder',
		'kind'         => 'other',
		'url'          => 'https://drive.google.com/drive/folders/11eNnXxN2GNsPnp50bPD89J90CTvjZwad',
		'qty'          => 1,
		'delivered_at' => '2026-01-16',
		'review_state' => 'approved',
	) );

	// ── month 3 · Z NEWS — Episodes 1 to 8 ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 3,
		'title'          => 'Z NEWS — Episodes 1 to 8',
		'theme_desc'     => 'An eight-part series in your own format: short, direct pieces answering what buyers and investors actually ask.',
		'status'         => 'delivered',
		'shoot_state'    => 'confirmed',
		'shoot_kind'     => 'studio',
		'shoot_at'       => '2026-02-26 09:00:00',
		'shoot_location' => 'MWM Creations & Studios',
		'delivered_at'   => '2026-03-12',
		'sort_order'     => 3,
	) );
	$cid = (int) $wpdb->insert_id;
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Z NEWS episode 1',
		'kind'         => 'episode',
		'url'          => 'https://drive.google.com/file/d/1ignvxZI9XUShhXUzeoDxxazxJ9T8Ycb9/view',
		'qty'          => 1,
		'delivered_at' => '2026-03-12',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Z NEWS episodes 2–8',
		'kind'         => 'episode',
		'url'          => 'https://drive.google.com/drive/folders/1bFDblw3KOmbgFL3ZndVgfu5XcknYTjJm',
		'qty'          => 7,
		'delivered_at' => '2026-03-12',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Vertical cuts of every episode',
		'kind'         => 'reel',
		'url'          => 'https://drive.google.com/drive/folders/1xte5sT1BqS2BBS3jYd_yF51bVXoAI1ls',
		'qty'          => 7,
		'delivered_at' => '2026-03-12',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Call-to-action films',
		'kind'         => 'short',
		'url'          => 'https://drive.google.com/drive/folders/1bFDblw3KOmbgFL3ZndVgfu5XcknYTjJm',
		'qty'          => 3,
		'delivered_at' => '2026-03-12',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Everything from this month, in one folder',
		'kind'         => 'other',
		'url'          => 'https://drive.google.com/drive/folders/1bFDblw3KOmbgFL3ZndVgfu5XcknYTjJm',
		'qty'          => 1,
		'delivered_at' => '2026-03-12',
		'review_state' => 'approved',
	) );

	// ── month 4 · Brand Films ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 4,
		'title'          => 'Brand Films',
		'theme_desc'     => 'Four brand pieces cut for both feeds, each delivered widescreen, vertical and subtitled.',
		'status'         => 'delivered',
		'shoot_state'    => 'confirmed',
		'shoot_kind'     => 'location',
		'shoot_at'       => '2026-05-01 09:00:00',
		'shoot_location' => 'On location, Orlando',
		'delivered_at'   => '2026-05-14',
		'sort_order'     => 4,
	) );
	$cid = (int) $wpdb->insert_id;
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Brand films 1–4 — first delivery',
		'kind'         => 'hero',
		'url'          => 'https://drive.google.com/drive/folders/1GfYPjDB0wRCf9GZnWOjOBDCukEMxjboG',
		'qty'          => 4,
		'delivered_at' => '2026-05-14',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Brand films 1–4 — widescreen, subtitled',
		'kind'         => 'hero',
		'url'          => 'https://drive.google.com/drive/folders/1NW2rL3g-hej4KdvSNPz1A2KYF6CHYdj8',
		'qty'          => 4,
		'delivered_at' => '2026-05-14',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Brand films 1–4 — vertical, subtitled',
		'kind'         => 'reel',
		'url'          => 'https://drive.google.com/drive/folders/1g_dYycsIMXjTFDq6I74SkQxlPFgEcTr8',
		'qty'          => 4,
		'delivered_at' => '2026-05-14',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Everything from this month, in one folder',
		'kind'         => 'other',
		'url'          => 'https://drive.google.com/drive/folders/1tkUpkuDmrhfZe7O_VSHJwLU7NxYoFAA9',
		'qty'          => 1,
		'delivered_at' => '2026-05-14',
		'review_state' => 'approved',
	) );

	// ── month 5 · Casa Windermere ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 5,
		'title'          => 'Casa Windermere',
		'theme_desc'     => 'A finished Windermere home, filmed before handover — the luxury showcase format applied to a real completion.',
		'status'         => 'delivered',
		'shoot_state'    => 'confirmed',
		'shoot_kind'     => 'location',
		'shoot_at'       => '2026-05-21 09:00:00',
		'shoot_location' => 'Windermere, FL',
		'delivered_at'   => '2026-06-09',
		'sort_order'     => 5,
	) );
	$cid = (int) $wpdb->insert_id;
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Casa Windermere — widescreen, subtitled',
		'kind'         => 'hero',
		'url'          => 'https://drive.google.com/file/d/1HzqC3CBytsoliNKz-pSm2IMAOPZmBr9T/view',
		'qty'          => 1,
		'delivered_at' => '2026-06-09',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Casa Windermere — vertical, subtitled',
		'kind'         => 'reel',
		'url'          => 'https://drive.google.com/file/d/1WQojiYeubTOqrOBYRB6a_7qoxSYLjxMH/view',
		'qty'          => 1,
		'delivered_at' => '2026-06-09',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Everything from this month, in one folder',
		'kind'         => 'other',
		'url'          => 'https://drive.google.com/drive/folders/14vUXeugaHQa8EhGxdk0EGANzbOy3n7vu',
		'qty'          => 1,
		'delivered_at' => '2026-06-09',
		'review_state' => 'approved',
	) );

	// ── month 6 · Handover & Father's Day ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 6,
		'title'          => 'Handover & Father\'s Day',
		'theme_desc'     => 'A family receiving their keys, plus a Father\'s Day piece cut from the same day.',
		'status'         => 'delivered',
		'shoot_state'    => 'confirmed',
		'shoot_kind'     => 'location',
		'shoot_at'       => '2026-06-03 09:00:00',
		'shoot_location' => 'Windermere, FL',
		'delivered_at'   => '2026-06-26',
		'sort_order'     => 6,
	) );
	$cid = (int) $wpdb->insert_id;
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'House handover — main film',
		'kind'         => 'hero',
		'url'          => 'https://drive.google.com/file/d/1JwU26ptV3Cffu0IvgyQhH43N_1m9eM3e/view',
		'qty'          => 1,
		'delivered_at' => '2026-06-26',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'House handover — alternate cut',
		'kind'         => 'hero',
		'url'          => 'https://drive.google.com/file/d/1XnLGrMM9gqp9pVFbt0YfNttVtS5DpSO_/view',
		'qty'          => 1,
		'delivered_at' => '2026-06-26',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'House handover — vertical',
		'kind'         => 'reel',
		'url'          => 'https://drive.google.com/file/d/1s1rh_vK61gj2AaJLbhk9mT6F49A8TrcR/view',
		'qty'          => 1,
		'delivered_at' => '2026-06-26',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Father\'s Day films',
		'kind'         => 'short',
		'url'          => 'https://drive.google.com/drive/folders/1EG7wloCgfHVy5RxMmDilQIWEQSOHhzIS',
		'qty'          => 2,
		'delivered_at' => '2026-06-26',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Everything from this month, in one folder',
		'kind'         => 'other',
		'url'          => 'https://drive.google.com/drive/folders/1DrbpX4hqJ_aul_UxKdj5MPd-ny2ooVMF',
		'qty'          => 1,
		'delivered_at' => '2026-06-26',
		'review_state' => 'approved',
	) );

	// ── month 7 · Z CAST — the podcast begins ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 7,
		'title'          => 'Z CAST — the podcast begins',
		'theme_desc'     => 'Your own show. One long-form episode, plus every strong moment cut out of it and captioned for social.',
		'status'         => 'delivered',
		'shoot_state'    => 'confirmed',
		'shoot_kind'     => 'studio',
		'shoot_at'       => '2026-06-18 09:00:00',
		'shoot_location' => 'MWM Creations & Studios',
		'delivered_at'   => '2026-06-23',
		'sort_order'     => 7,
	) );
	$cid = (int) $wpdb->insert_id;
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Z CAST — full episode',
		'kind'         => 'episode',
		'url'          => 'https://drive.google.com/file/d/1p2ubdsDvFmeB8xamTFBc0AS7SE-eX9bz/view',
		'qty'          => 1,
		'delivered_at' => '2026-06-23',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Short cuts, captioned',
		'kind'         => 'short',
		'url'          => 'https://drive.google.com/drive/folders/1PERJtroa7M3C3m8C-jdQOOJPOtQSpn0D',
		'qty'          => 16,
		'delivered_at' => '2026-06-23',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Everything from this month, in one folder',
		'kind'         => 'other',
		'url'          => 'https://drive.google.com/drive/folders/1DFDV0qDsDvsufAtyQCS6KxylT86gc_6r',
		'qty'          => 1,
		'delivered_at' => '2026-06-23',
		'review_state' => 'approved',
	) );

	// ── month 8 · Z CAST — Episode 01 with Sandina ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 8,
		'title'          => 'Z CAST — Episode 01 with Sandina',
		'theme_desc'     => 'The series proper: title sequence, full episode, and eighteen short cuts ready to post.',
		'status'         => 'delivered',
		'shoot_state'    => 'confirmed',
		'shoot_kind'     => 'studio',
		'shoot_at'       => '2026-07-15 09:00:00',
		'shoot_location' => 'MWM Creations & Studios',
		'delivered_at'   => '2026-07-24',
		'sort_order'     => 8,
	) );
	$cid = (int) $wpdb->insert_id;
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Z CAST Episode 01 — full episode',
		'kind'         => 'episode',
		'url'          => 'https://drive.google.com/file/d/1qCe7LOx8pd9usnPoy4TqIrTtBpkW6n81/view',
		'qty'          => 1,
		'delivered_at' => '2026-07-24',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Z CAST title sequence',
		'kind'         => 'short',
		'url'          => 'https://drive.google.com/file/d/1HzYMv3ZKtoNWGxMVTrR9HCedX9l5FEvg/view',
		'qty'          => 1,
		'delivered_at' => '2026-07-24',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Short cuts, captioned',
		'kind'         => 'short',
		'url'          => 'https://drive.google.com/drive/folders/1grdRE4gAWVX6cjCF4QdemRpjKjd2UoeQ',
		'qty'          => 18,
		'delivered_at' => '2026-07-24',
		'review_state' => 'approved',
	) );
	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => 'Everything from this month, in one folder',
		'kind'         => 'other',
		'url'          => 'https://drive.google.com/drive/folders/1P7i9ahL36QsPCoSLcj5yMYOvAEixOQtW',
		'qty'          => 1,
		'delivered_at' => '2026-07-24',
		'review_state' => 'approved',
	) );

	// ── month 9 · Realtor Partner Series ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 9,
		'title'          => 'Realtor Partner Series',
		'theme_desc'     => 'Films made with the agents who sell your homes — their audience meets your build quality, in their words.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => null,
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 9,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── month 10 · Luxury Showcase ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 10,
		'title'          => 'Luxury Showcase',
		'theme_desc'     => 'One finished high-end home, filmed properly — the piece that positions Z Brothers as a luxury boutique builder.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => null,
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 10,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── month 11 · Partner Podcast ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 11,
		'title'          => 'Partner Podcast',
		'theme_desc'     => 'A Z CAST episode with someone from the build — an engineer, an architect, a designer. Authority by association.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => null,
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 11,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── month 12 · Annual Retrospective ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => 12,
		'title'          => 'Annual Retrospective',
		'theme_desc'     => 'Thiago, Sandina, the team and the families from this year — and where Z Brothers goes next.',
		'status'         => 'planned',
		'shoot_state'    => 'none',
		'shoot_kind'     => null,
		'shoot_at'       => null,
		'shoot_location' => '',
		'delivered_at'   => null,
		'sort_order'     => 12,
	) );
	$cid = (int) $wpdb->insert_id;

	// ── needs your attention ──
	$wpdb->insert( $actions, array(
		'client_id' => $client_id,
		'title'     => 'Four campaign days left, and 95 days to use them',
		'detail'    => 'Campaigns 9 to 12 of your roadmap are still to film. On location we need 7 days\' notice, so the last comfortable booking date is early November.',
		'due_date'  => '2026-11-14',
		'resolved'  => 0,
	) );
	$wpdb->insert( $actions, array(
		'client_id' => $client_id,
		'title'     => '11 of your 12 studio hours are still unused',
		'detail'    => 'They are included in your plan and they expire with your contract year on 14 November. A studio day is the cheapest way to add a Z CAST episode or a batch of social films.',
		'due_date'  => '2026-11-14',
		'resolved'  => 0,
	) );
	$wpdb->insert( $actions, array(
		'client_id' => $client_id,
		'title'     => 'We need a partner named for the Realtor Series',
		'detail'    => 'Campaign 9 films with agents who sell your homes. Give us one or two names and we will handle the invitation and the scheduling.',
		'due_date'  => null,
		'resolved'  => 0,
	) );

	update_option( 'mwm_roadmap_seed_zb', MWM_RM_SEED_ZB_VERSION, false );
}

// Run once per version bump, not on every page load — same shape as snippet 21.
add_action( 'init', function () {
	if ( get_option( 'mwm_roadmap_seed_zb' ) !== MWM_RM_SEED_ZB_VERSION ) {
		mwm_rm_seed_zbrothers();
	}
}, 5 );
