#!/usr/bin/env python3
"""
Generates wp-snippet-23-zbrothers-seed.php from zbrothers_data.json.

ONE source of truth (the JSON), two consumers (the local harness and this
seeder), so the portal Michael reviewed and the portal WordPress serves cannot
drift. Do not hand-edit the generated PHP.
"""
import json, textwrap

D = json.load(open('/home/claude/zbrothers_data.json'))
c = D['client']

def php(s):
    """PHP single-quoted string literal."""
    if s is None:
        return 'null'
    return "'" + str(s).replace('\\', '\\\\').replace("'", "\\'") + "'"

out = []
w = out.append

w("""<?php
// Code Snippets plugin — MWM ROADMAP™ · SEED: Zerlotini Brothers Construction
// WP Code Snippets ID 23 · DEV · Aug 11 2026 · seed v1
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

define( 'MWM_RM_SEED_ZB_VERSION', '1' );

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
""")

w(f"""
	$email = {php(c['email'])};

	// ── client ───────────────────────────────────────────────────────────
	$client_id = (int) $wpdb->get_var( $wpdb->prepare( "SELECT id FROM {{$clients}} WHERE email = %s", $email ) );

	if ( ! $client_id ) {{
		// Same alphabet as the studio portal — no ambiguous characters, because
		// a client reads this off an email and types it on a phone.
		$chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
		$code  = '';
		for ( $i = 0; $i < 6; $i++ ) {{ $code .= $chars[ wp_rand( 0, strlen( $chars ) - 1 ) ]; }}

		$wpdb->insert( $clients, array(
			'client_name'          => {php(c['client_name'])},
			'company'              => {php(c['company'])},
			'email'                => $email,
			'access_code'          => wp_hash_password( $code ),
			'plan'                 => {php(c['plan'])},
			'campaigns_allowed'    => {c['campaigns_allowed']},
			'captures_allowed'     => {c['captures_allowed']},
			'studio_hours_allowed' => {c['studio_hours_allowed']},
			'conversions_used'     => {c['conversions_used']},
			'contract_start'       => {php(c['contract_start'])},
			'contract_end'         => {php(c['contract_end'])},
			'strategist'           => {php(c['strategist'])},
			'language'             => {php(c['language'])},
			'status'               => {php(c['status'])},
		) );
		$client_id = (int) $wpdb->insert_id;

		// Read once from wp-admin, then delete. Not logged, not emailed.
		update_option( 'mwm_roadmap_seed_code_once', $code, false );
	}}

	if ( ! $client_id ) {{
		error_log( '[MWM ROADMAP seed] aborted — could not create or find the client row.' );
		return;
	}}

	// ── rebuild this client's campaigns, assets and actions ──────────────
	// Scoped to $client_id throughout. Nothing belonging to another client is
	// read, updated or deleted by any statement below.
	$old = $wpdb->get_col( $wpdb->prepare( "SELECT id FROM {{$campaigns}} WHERE client_id = %d", $client_id ) );
	if ( $old ) {{
		$in = implode( ',', array_map( 'intval', $old ) );
		$wpdb->query( "DELETE FROM {{$assets}} WHERE campaign_id IN ({{$in}})" );
		$wpdb->query( $wpdb->prepare( "DELETE FROM {{$campaigns}} WHERE client_id = %d", $client_id ) );
	}}
	$wpdb->query( $wpdb->prepare( "DELETE FROM {{$actions}} WHERE client_id = %d", $client_id ) );
""")

# ---- campaigns ----
for cam in D['campaigns']:
    w(f"""
	// ── month {cam['month_no']} · {cam['title']} ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => {cam['month_no']},
		'title'          => {php(cam['title'])},
		'theme_desc'     => {php(cam['theme_desc'])},
		'status'         => {php(cam['status'])},
		'shoot_state'    => {php(cam['shoot_state'])},
		'shoot_kind'     => {php(cam['shoot_kind'])},
		'shoot_at'       => {php(cam['shoot_at'])},
		'shoot_location' => {php(cam['shoot_location'])},
		'delivered_at'   => {php(cam['delivered_at'])},
		'sort_order'     => {cam['month_no']},
	) );
	$cid = (int) $wpdb->insert_id;""")

    rows = list(cam['assets'])
    if cam.get('folder_url'):
        rows.append({
            'title': 'Everything from this month, in one folder',
            'kind': 'other',
            'url': cam['folder_url'],
            'qty': 1,
            'review_state': 'approved',
        })
    for a in rows:
        w(f"""	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => {php(a['title'])},
		'kind'         => {php(a['kind'])},
		'url'          => {php(a['url'])},
		'qty'          => {a['qty']},
		'delivered_at' => {php(cam['delivered_at'])},
		'review_state' => {php(a['review_state'])},
	) );""")

# ---- actions ----
w("\n	// ── needs your attention ──")
for a in D['actions']:
    w(f"""	$wpdb->insert( $actions, array(
		'client_id' => $client_id,
		'title'     => {php(a['title'])},
		'detail'    => {php(a['detail'])},
		'due_date'  => {php(a['due_date'])},
		'resolved'  => 0,
	) );""")

w("""
	update_option( 'mwm_roadmap_seed_zb', MWM_RM_SEED_ZB_VERSION, false );
}

// Run once per version bump, not on every page load — same shape as snippet 21.
add_action( 'init', function () {
	if ( get_option( 'mwm_roadmap_seed_zb' ) !== MWM_RM_SEED_ZB_VERSION ) {
		mwm_rm_seed_zbrothers();
	}
}, 5 );
""")

open('/home/claude/wp-snippet-23-zbrothers-seed.php', 'w').write('\n'.join(out))
print('written')
