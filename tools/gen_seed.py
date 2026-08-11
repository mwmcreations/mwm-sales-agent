#!/usr/bin/env python3
"""
Generates a WordPress seeder snippet from a client JSON.

    gen_seed.py <data.json> <key> <version> <out.php>

ONE generator, one JSON per client, so the portal reviewed locally and the portal
WordPress serves cannot drift. The <key> namespaces the guard option
(mwm_roadmap_seed_<key>) and every function name, so seeding a second client can
never re-run, redeclare against, or clobber the first.

Do not hand-edit the generated PHP.
"""
import json, sys

DATA, KEY, VER, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
D = json.load(open(DATA))
c = D['client']
K = KEY.lower()


def php(s):
    """PHP literal — a quoted string, or a bare null."""
    if s is None or s == '':
        return "''" if s == '' else 'null'
    return "'" + str(s).replace('\\', '\\\\').replace("'", "\\'") + "'"


def num(v):
    return 'null' if v is None else str(v)


out = []
w = out.append

w(f"""<?php
// Code Snippets plugin — MWM ROADMAP™ · SEED: {c['client_name']}
// DEV · Aug 11 2026 · seed v{VER} · key "{K}"
//
// GENERATED from docs/roadmap-seed/{DATA.split('/')[-1]} by tools/gen_seed.py.
// DO NOT HAND-EDIT — change the JSON and regenerate.
//
// 🔴 IDEMPOTENT and SCOPED TO ONE CLIENT. Guarded by mwm_roadmap_seed_{K}. Bump the
// version to re-seed; that path deletes THIS client's campaigns, assets and actions
// and rebuilds them. Every statement is filtered by this client's id — no other
// client is read, updated or deleted.
//
// 🔴 The access code is generated here, stored hashed, and the plaintext is parked in
// mwm_roadmap_seed_code_once for the bootstrap snippet to mail to Michael and delete.
// It is never logged and never returned to an agent.

if ( ! defined( 'ABSPATH' ) ) {{ exit; }}

define( 'MWM_RM_SEED_{K.upper()}_VERSION', '{VER}' );

function mwm_rm_seed_{K}() {{

	global $wpdb;
	$p = $wpdb->prefix;
	$clients   = $p . 'mwm_roadmap_clients';
	$campaigns = $p . 'mwm_roadmap_campaigns';
	$assets    = $p . 'mwm_roadmap_assets';
	$actions   = $p . 'mwm_roadmap_actions';

	if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $clients ) ) !== $clients ) {{
		error_log( '[MWM ROADMAP seed {K}] aborted — schema missing. Is the schema snippet active?' );
		return;
	}}

	$email     = {php(c['email'])};
	$client_id = (int) $wpdb->get_var( $wpdb->prepare( "SELECT id FROM {{$clients}} WHERE email = %s", $email ) );

	if ( ! $client_id ) {{
		// Same alphabet as the studio portal — no ambiguous characters, because a
		// client reads this off an email and types it on a phone.
		$chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
		$code  = '';
		for ( $i = 0; $i < 6; $i++ ) {{ $code .= $chars[ wp_rand( 0, strlen( $chars ) - 1 ) ]; }}

		$wpdb->insert( $clients, array(
			'client_name'          => {php(c['client_name'])},
			'company'              => {php(c.get('company', ''))},
			'email'                => $email,
			'access_code'          => wp_hash_password( $code ),
			'plan'                 => {php(c['plan'])},
			'campaigns_allowed'    => {c['campaigns_allowed']},
			'captures_allowed'     => {c['captures_allowed']},
			'studio_hours_allowed' => {c['studio_hours_allowed']},
			'conversions_used'     => {c['conversions_used']},
			'contract_start'       => {num(c['contract_start']) if c['contract_start'] is None else php(c['contract_start'])},
			'contract_end'         => {num(c['contract_end']) if c['contract_end'] is None else php(c['contract_end'])},
			'strategist'           => {php(c['strategist'])},
			'language'             => {php(c['language'])},
			'status'               => {php(c['status'])},
			'studio_client_id'     => {num(c.get('studio_client_id'))},
		) );
		$client_id = (int) $wpdb->insert_id;
		update_option( 'mwm_roadmap_seed_code_once', $code, false );
	}}

	if ( ! $client_id ) {{
		error_log( '[MWM ROADMAP seed {K}] aborted — no client row.' );
		return;
	}}

	// Keep the plan facts current without ever touching the access code.
	$wpdb->update( $clients, array(
		'campaigns_allowed'    => {c['campaigns_allowed']},
		'captures_allowed'     => {c['captures_allowed']},
		'studio_hours_allowed' => {c['studio_hours_allowed']},
		'studio_client_id'     => {num(c.get('studio_client_id'))},
		'contract_start'       => {num(c['contract_start']) if c['contract_start'] is None else php(c['contract_start'])},
		'contract_end'         => {num(c['contract_end']) if c['contract_end'] is None else php(c['contract_end'])},
	), array( 'id' => $client_id ) );

	// 🔴 Rebuild ONLY the rows we author. A shoot the client has already requested
	// lives on the campaign row, so re-seeding would silently throw it away —
	// therefore campaigns are only wiped when none of them has been touched.
	$touched = (int) $wpdb->get_var( $wpdb->prepare(
		"SELECT COUNT(*) FROM {{$campaigns}} WHERE client_id = %d AND shoot_state <> 'none'", $client_id ) );

	if ( $touched > 0 ) {{
		error_log( '[MWM ROADMAP seed {K}] skipped campaign rebuild — client has live bookings.' );
		update_option( 'mwm_roadmap_seed_{K}', MWM_RM_SEED_{K.upper()}_VERSION, false );
		return;
	}}

	$old = $wpdb->get_col( $wpdb->prepare( "SELECT id FROM {{$campaigns}} WHERE client_id = %d", $client_id ) );
	if ( $old ) {{
		$in = implode( ',', array_map( 'intval', $old ) );
		$wpdb->query( "DELETE FROM {{$assets}} WHERE campaign_id IN ({{$in}})" );
		$wpdb->query( $wpdb->prepare( "DELETE FROM {{$campaigns}} WHERE client_id = %d", $client_id ) );
	}}
	$wpdb->query( $wpdb->prepare( "DELETE FROM {{$actions}} WHERE client_id = %d", $client_id ) );
""")

for cam in D['campaigns']:
    w(f"""
	// ── campaign {cam['month_no']} · {cam['title']} ──
	$wpdb->insert( $campaigns, array(
		'client_id'      => $client_id,
		'month_no'       => {cam['month_no']},
		'title'          => {php(cam['title'])},
		'theme_desc'     => {php(cam['theme_desc'])},
		'status'         => {php(cam['status'])},
		'shoot_state'    => {php(cam['shoot_state'])},
		'shoot_kind'     => {php(cam['shoot_kind'])},
		'shoot_at'       => {num(cam['shoot_at']) if cam['shoot_at'] is None else php(cam['shoot_at'])},
		'shoot_location' => {php(cam['shoot_location'])},
		'delivered_at'   => {num(cam['delivered_at']) if cam['delivered_at'] is None else php(cam['delivered_at'])},
		'sort_order'     => {cam['month_no']},
	) );
	$cid = (int) $wpdb->insert_id;""")

    rows = list(cam.get('assets') or [])
    if cam.get('folder_url'):
        rows.append({'title': 'Everything from this month, in one folder', 'kind': 'other',
                     'url': cam['folder_url'], 'qty': 1, 'review_state': 'approved'})
    for a in rows:
        w(f"""	$wpdb->insert( $assets, array(
		'campaign_id'  => $cid,
		'title'        => {php(a['title'])},
		'kind'         => {php(a['kind'])},
		'url'          => {php(a['url'])},
		'qty'          => {a['qty']},
		'delivered_at' => {num(cam['delivered_at']) if cam['delivered_at'] is None else php(cam['delivered_at'])},
		'review_state' => {php(a['review_state'])},
	) );""")

w("\n	// ── needs your attention ──")
for a in D['actions']:
    w(f"""	$wpdb->insert( $actions, array(
		'client_id' => $client_id,
		'title'     => {php(a['title'])},
		'detail'    => {php(a['detail'])},
		'due_date'  => {num(a['due_date']) if a['due_date'] is None else php(a['due_date'])},
		'resolved'  => 0,
	) );""")

w(f"""
	update_option( 'mwm_roadmap_seed_{K}', MWM_RM_SEED_{K.upper()}_VERSION, false );
}}

add_action( 'init', function () {{
	if ( get_option( 'mwm_roadmap_seed_{K}' ) !== MWM_RM_SEED_{K.upper()}_VERSION ) {{
		mwm_rm_seed_{K}();
	}}
}}, 5 );
""")

open(OUT, 'w').write('\n'.join(out))
print('written', OUT)
