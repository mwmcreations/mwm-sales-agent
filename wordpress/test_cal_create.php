<?php
// PATCH #131 — harness for cal_sync_created(). Slices the method out of the
// SHIPPING plugin file and runs it against stubs; no WordPress needed.
define('HOUR_IN_SECONDS', 3600);
$OPTS = array();
function sanitize_text_field($s){ return trim(strip_tags((string)$s)); }
function get_option($k,$d=false){ global $OPTS; return array_key_exists($k,$OPTS)?$OPTS[$k]:$d; }
function update_option($k,$v,$a=null){ global $OPTS; $OPTS[$k]=$v; return true; }
class WP_REST_Response { public $data; public $status; function __construct($d,$s=200){ $this->data=$d; $this->status=$s; } }
class FakeDB {
  public $clients = array(); public $bookings = array();
  function prepare($q){ $a=func_get_args(); array_shift($a); foreach($a as $v){ $q=preg_replace('/%[ds]/', is_int($v)?(string)$v:"'".$v."'", $q, 1);} return $q; }
  function get_results($q){ return $this->clients; }
  function get_row($q){ if(preg_match('/id = (\d+)/',$q,$m)){ $id=(int)$m[1]; return isset($this->bookings[$id])?$this->bookings[$id]:null; } return null; }
}
$wpdb = new FakeDB();
$src = file_get_contents(__DIR__.'/mwm-studio-booking.php');
if(!preg_match('/(\tprivate function cal_sync_created\(.*?)\n\tpublic function handle_calendar_sync/s',$src,$m)){ fwrite(STDERR,"slice failed\n"); exit(2); }
$method = $m[1];
$cls = 'class Harness { public $bookings_table="b"; public $clients_table="c"; public $writes=array(); public $refuse=null; public $next_id=100;
  function get_client($id){ global $wpdb; foreach($wpdb->clients as $c){ if((int)$c->id===(int)$id) return $c; } return null; }
  function hours_used_in_contract($id,$a=null,$b=null){ return 7.5; }
  function event_bid($b){ return (string)$b->id; }
  function booking_client_label($id,$b=null){ $c=$this->get_client($id); return $c?$c->name:"?"; }
  function cal_booking_snapshot($b){ return array("date"=>$b->booking_date,"start"=>substr($b->start_time,0,5),"end"=>substr($b->end_time,0,5),"duration"=>(float)$b->duration_hours,"status"=>$b->status); }
  function admin_write_booking($id,$f,$o){ global $wpdb; $this->writes[]=array($id,$f,$o); if($this->refuse) return array("ok"=>false,"message"=>$this->refuse); $bid=$this->next_id++; $end=date("H:i:s", strtotime($f["booking_date"]." ".$f["start_time"].":00")+(int)round($f["duration_hours"]*3600));
    $wpdb->bookings[$bid]=(object)array("id"=>$bid,"client_id"=>$f["client_id"],"booking_date"=>$f["booking_date"],"start_time"=>$f["start_time"].":00","end_time"=>$end,"duration_hours"=>$f["duration_hours"],"status"=>"confirmed","reschedule_count"=>0); return array("ok"=>true,"booking_id"=>$bid,"warnings"=>array()); }
  function call($p){ return $this->cal_sync_created($p); }
'.$method."\n}";
eval($cls);
$P=0;$F=0;
function check($l,$g,$w){ global $P,$F; if($g===$w){$P++; echo "  PASS  $l\n";} else {$F++; echo "  FAIL  $l\n     got=".var_export($g,true)."\n    want=".var_export($w,true)."\n";} }
function cl($id,$name,$active=1){ return (object)array("id"=>$id,"name"=>$name,"active"=>$active,"contract_hours"=>12.0,"contract_start_date"=>null,"contract_end_date"=>null); }
function pl($name,$eid="ev1",$s="14:15",$e="15:15"){ return array("action"=>"created","event_id"=>$eid,"client_name"=>$name,"date"=>"2026-09-24","start_time"=>$s,"end_time"=>$e); }
function fresh($clients){ global $wpdb,$OPTS; $OPTS=array(); $wpdb->clients=$clients; $wpdb->bookings=array(); return new Harness(); }

$h=fresh(array(cl(1,"Jonathan Pineda"),cl(2,"Camila Rocha")));
$r=$h->call(pl("Jonathan Pineda"));
check("exact name books", $r->data["state"], "created");
check("...one write", count($h->writes), 1);
check("...for that client", $h->writes[0][1]["client_id"], 1);
check("...creating, not editing", $h->writes[0][0], 0);
check("...1 hour", (float)$h->writes[0][1]["duration_hours"], 1.0);
check("...push_calendar OFF (calendar already holds it)", $h->writes[0][2]["push_calendar"], false);
check("...no client notification", $h->writes[0][2]["notify_client"], false);
check("...audited as a calendar create", $h->writes[0][2]["action"], "booking.calendar_create");
check("...returns the booking id", $r->data["booking_id"], 100);
check("...and the event bid", $r->data["event_bid"], "100");
check("...and the package position", array($r->data["hours_used"],$r->data["hours_total"]), array(7.5,12.0));
$r2=$h->call(pl("Jonathan Pineda"));
check("the same event again answers exists", $r2->data["state"], "exists");
check("...and does NOT book twice", count($h->writes), 1);

$h=fresh(array(cl(1,"Jonathan Pineda")));
check("case and spacing are ignored", $h->call(pl("  jonathan   PINEDA "))->data["state"], "created");

$h=fresh(array(cl(1,"Jonathan Pineda"),cl(2,"Camila Rocha")));
$r=$h->call(pl("Jon Pineda"));
check("an unknown name books nothing", $r->data["state"], "no_match");
check("...no write", count($h->writes), 0);
check("...and suggests a close name", strpos($r->data["message"],"Did you mean: Jonathan Pineda")!==false, true);

$h=fresh(array(cl(1,"Maria Silva"),cl(2,"Maria Silva")));
$r=$h->call(pl("Maria Silva"));
check("two clients with one name books nothing", $r->data["state"], "ambiguous");
check("...no write", count($h->writes), 0);

$h=fresh(array(cl(1,"Maria Silva",0),cl(2,"Maria Silva",1)));
$r=$h->call(pl("Maria Silva"));
check("...unless exactly one of them is active", $r->data["state"], "created");
check("...and it picks the active one", $h->writes[0][1]["client_id"], 2);

$h=fresh(array(cl(1,"Old Client",0)));
check("an inactive client is refused", $h->call(pl("Old Client"))->data["state"], "refused");
check("...no write", count($h->writes), 0);

$h=fresh(array(cl(1,"Jonathan Pineda")));
check("a bad time is a 400", $h->call(pl("Jonathan Pineda","ev1","2pm","3pm"))->status, 400);
check("a missing event id is a 400", $h->call(pl("Jonathan Pineda",""))->status, 400);
check("an event past midnight is refused", $h->call(pl("Jonathan Pineda","ev1","23:00","01:00"))->data["state"], "refused");

$h=fresh(array(cl(1,"Jonathan Pineda")));
$h->refuse="Duration must be a multiple of 0.25 hours (15 minutes).";
$r=$h->call(pl("Jonathan Pineda","ev1","14:00","14:50"));
check("a refusal from the write path is passed on", $r->data["state"], "refused");
check("...with its reason", $r->data["message"], "Duration must be a multiple of 0.25 hours (15 minutes).");
check("...and nothing is remembered for that event", get_option("mwm_studio_calcreate_".md5("ev1"),0), 0);

echo "\n  TOTAL: $P passed, $F failed\n";
exit($F?1:0);
