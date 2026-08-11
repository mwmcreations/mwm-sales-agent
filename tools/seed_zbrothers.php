<?php
/**
 * GENERATED SHAPE — reads zbrothers_data.json and fills $wpdb->data for the
 * local harness. The JSON is the single source; do not hand-edit rows here.
 */

$J = json_decode( file_get_contents( __DIR__ . '/zbrothers_data.json' ), true );

$o = function ( array $a ) { return (object) $a; };

$client = $J['client'];
$wpdb->data['wp_mwm_roadmap_clients'] = array( $o( array(
	'id'                   => 1,
	'client_name'          => $client['client_name'],
	'company'              => $client['company'],
	'email'                => $client['email'],
	'access_code'          => 'ZBR7K2',           // harness only — real code is hashed
	'plan'                 => $client['plan'],
	'campaigns_allowed'    => $client['campaigns_allowed'],
	'captures_allowed'     => $client['captures_allowed'],
	'studio_hours_allowed' => $client['studio_hours_allowed'],
	'conversions_used'     => $client['conversions_used'],
	'contract_start'       => $client['contract_start'],
	'contract_end'         => $client['contract_end'],
	'strategist'           => $client['strategist'],
	'language'             => $client['language'],
	'stripe_customer_id'   => '',
	'status'               => $client['status'],
) ) );

$campaigns = array();
$assets    = array();
$cid       = 100;
$aid       = 1000;

foreach ( $J['campaigns'] as $c ) {
	$cid++;
	$campaigns[] = $o( array(
		'id'             => $cid,
		'client_id'      => 1,
		'month_no'       => $c['month_no'],
		'title'          => $c['title'],
		'theme_desc'     => $c['theme_desc'],
		'hero_spec'      => '',
		'status'         => $c['status'],
		'shoot_state'    => $c['shoot_state'],
		'shoot_kind'     => $c['shoot_kind'],
		'shoot_at'       => $c['shoot_at'],
		'shoot_end'      => null,
		'shoot_location' => $c['shoot_location'],
		'requested_by'   => '',
		'requested_at'   => null,
		'hold_expires_at'=> null,
		'confirmed_by'   => '',
		'confirmed_at'   => null,
		'gcal_event_id'  => '',
		'delivered_at'   => $c['delivered_at'],
		'sort_order'     => $c['month_no'],
	) );

	foreach ( $c['assets'] as $a ) {
		$aid++;
		$assets[] = $o( array(
			'id'            => $aid,
			'campaign_id'   => $cid,
			'title'         => $a['title'],
			'kind'          => $a['kind'],
			'url'           => $a['url'],
			'qty'           => $a['qty'],
			'duration_secs' => null,
			'delivered_at'  => $c['delivered_at'],
			'review_state'  => $a['review_state'],
			'revision_no'   => 1,
			'reviewed_by'   => '',
			'reviewed_at'   => null,
			'sheet_row_key' => '',
		) );
	}

	// "View everything from this month" row — one click into their own folder.
	if ( ! empty( $c['folder_url'] ) ) {
		$aid++;
		$assets[] = $o( array(
			'id'            => $aid,
			'campaign_id'   => $cid,
			'title'         => 'Everything from this month, in one folder',
			'kind'          => 'other',
			'url'           => $c['folder_url'],
			'qty'           => 1,
			'duration_secs' => null,
			'delivered_at'  => $c['delivered_at'],
			'review_state'  => 'approved',
			'revision_no'   => 1,
			'reviewed_by'   => '',
			'reviewed_at'   => null,
			'sheet_row_key' => 'FOLDER',
		) );
	}
}

$wpdb->data['wp_mwm_roadmap_campaigns'] = $campaigns;
$wpdb->data['wp_mwm_roadmap_assets']    = $assets;

$actions = array();
$acid    = 1;
foreach ( $J['actions'] as $a ) {
	$actions[] = $o( array(
		'id'          => $acid++,
		'client_id'   => 1,
		'campaign_id' => null,
		'title'       => $a['title'],
		'detail'      => $a['detail'],
		'due_date'    => $a['due_date'],
		'resolved'    => 0,
		'resolved_at' => null,
		'created_at'  => '2026-08-11 09:00:00',
	) );
}
$wpdb->data['wp_mwm_roadmap_actions']      = $actions;
$wpdb->data['wp_mwm_roadmap_participants'] = array();
$wpdb->data['wp_mwm_roadmap_captures']     = array();
