<?php
/** Local harness seed for Dr. Bolfer — reads bolfer_data.json, same shape as the WP seeder. */
$J = json_decode( file_get_contents( __DIR__ . '/bolfer_data.json' ), true );
$o = function ( array $a ) { return (object) $a; };
$c = $J['client'];
$wpdb->data['wp_mwm_roadmap_clients'] = array( $o( array(
  'id'=>1,'client_name'=>$c['client_name'],'company'=>$c['company'],'email'=>$c['email'],
  'access_code'=>'TEST','plan'=>$c['plan'],'campaigns_allowed'=>$c['campaigns_allowed'],
  'captures_allowed'=>$c['captures_allowed'],'studio_hours_allowed'=>$c['studio_hours_allowed'],
  'conversions_used'=>0,'contract_start'=>$c['contract_start'],'contract_end'=>$c['contract_end'],
  'strategist'=>$c['strategist'],'language'=>'en','stripe_customer_id'=>'','status'=>'active',
  'studio_client_id'=>null,
) ) );
$cid=100; $camps=array();
foreach ( $J['campaigns'] as $cm ) { $cid++;
  $camps[] = $o( array('id'=>$cid,'client_id'=>1,'month_no'=>$cm['month_no'],'title'=>$cm['title'],
    'theme_desc'=>$cm['theme_desc'],'hero_spec'=>'','status'=>$cm['status'],'shoot_state'=>$cm['shoot_state'],
    'shoot_kind'=>$cm['shoot_kind'],'shoot_at'=>$cm['shoot_at'],'shoot_end'=>null,
    'shoot_location'=>$cm['shoot_location'],'requested_by'=>'','requested_at'=>null,'hold_expires_at'=>null,
    'confirmed_by'=>'','confirmed_at'=>null,'gcal_event_id'=>'','delivered_at'=>$cm['delivered_at'],
    'sort_order'=>$cm['month_no']) );
}
$wpdb->data['wp_mwm_roadmap_campaigns']=$camps;
$wpdb->data['wp_mwm_roadmap_assets']=array();
$acts=array(); $i=1;
foreach ( $J['actions'] as $a ) { $acts[] = $o(array('id'=>$i++,'client_id'=>1,'campaign_id'=>null,
  'title'=>$a['title'],'detail'=>$a['detail'],'due_date'=>$a['due_date'],'resolved'=>0,
  'resolved_at'=>null,'created_at'=>'2026-08-11 09:00:00')); }
$wpdb->data['wp_mwm_roadmap_actions']=$acts;
$wpdb->data['wp_mwm_roadmap_participants']=array();
$wpdb->data['wp_mwm_roadmap_captures']=array();
