<?php
/**
 * Local render harness for wp-snippet-22-roadmap-portal.php
 *
 * Stubs just enough WordPress to render the shortcode against in-memory
 * Z Brothers data. Two jobs:
 *   1. Prove the snippet renders before it goes anywhere near production.
 *   2. Produce the standalone offline copy for the meeting.
 *
 * Usage: php harness.php > zbrothers_portal.html
 */

define( 'ABSPATH', __DIR__ . '/' );
define( 'HOUR_IN_SECONDS', 3600 );
define( 'MINUTE_IN_SECONDS', 60 );
define( 'DAY_IN_SECONDS', 86400 );

// ── WP function stubs ───────────────────────────────────────────────────
function wp_salt( $s = '' ) { return 'harness-salt'; }
function is_ssl() { return true; }
function nocache_headers() {}
function wp_unslash( $v ) { return $v; }
function sanitize_email( $v ) { return filter_var( $v, FILTER_SANITIZE_EMAIL ); }
function sanitize_text_field( $v ) { return trim( strip_tags( (string) $v ) ); }
function is_email( $v ) { return (bool) filter_var( $v, FILTER_VALIDATE_EMAIL ); }
function esc_html( $v ) { return htmlspecialchars( (string) $v, ENT_QUOTES, 'UTF-8' ); }
function esc_attr( $v ) { return htmlspecialchars( (string) $v, ENT_QUOTES, 'UTF-8' ); }
function esc_url( $v ) { return htmlspecialchars( (string) $v, ENT_QUOTES, 'UTF-8' ); }
function wp_check_password( $p, $h ) { return $p === $h; }
function wp_hash_password( $p ) { return $p; }
function wp_nonce_field( $a = '', $b = '' ) { echo '<input type="hidden" name="' . esc_attr( $b ) . '" value="x">'; }
function wp_verify_nonce( $a, $b ) { return true; }
function get_transient( $k ) { return false; }
function set_transient( $k, $v, $t ) {}
function delete_transient( $k ) {}
function add_shortcode( $tag, $cb ) { $GLOBALS['__sc'][ $tag ] = $cb; }
function apply_filters( $tag, $value ) { return $value; }
function add_filter( $tag, $cb, $pri = 10, $args = 1 ) {}
function is_singular( $t = '' ) { return true; }
function get_post( $id = null ) { return null; }
function has_shortcode( $c, $t ) { return false; }
function get_page_by_path( $p ) { return null; }
function home_url( $p = '' ) { return 'https://mwmcreations.com' . $p; }
function current_time( $type ) { return $type === 'timestamp' ? time() : date( 'Y-m-d' ); }
function date_i18n( $fmt, $ts ) { return date( $fmt, $ts ); }
function add_query_arg( $k, $v = null ) { return '#'; }
function remove_query_arg( $k ) { return '#'; }
function wp_safe_redirect( $u ) {}
function wp_list_pluck( $rows, $field ) {
	return array_map( function ( $r ) use ( $field ) { return $r->$field; }, $rows );
}
function setcookie_stub() {}

// ── fake $wpdb ──────────────────────────────────────────────────────────
class HarnessWPDB {
	public $prefix = 'wp_';
	public $data   = array();

	public function prepare( $sql, ...$args ) {
		foreach ( $args as $a ) {
			$sql = preg_replace( '/%d/', (string) (int) $a, $sql, 1 );
			$sql = preg_replace( '/%s/', "'" . addslashes( (string) $a ) . "'", $sql, 1 );
		}
		return $sql;
	}
	private function table_of( $sql ) {
		if ( preg_match( '/FROM\s+(\w+)/i', $sql, $m ) ) { return $m[1]; }
		return '';
	}
	public function get_row( $sql ) {
		$rows = $this->get_results( $sql );
		return $rows ? $rows[0] : null;
	}
	public function get_results( $sql ) {
		$t    = $this->table_of( $sql );
		$rows = isset( $this->data[ $t ] ) ? $this->data[ $t ] : array();

		// good enough for the handful of shapes the snippet issues
		if ( preg_match( '/client_id = (\d+)/', $sql, $m ) ) {
			$rows = array_values( array_filter( $rows, fn( $r ) => (int) $r->client_id === (int) $m[1] ) );
		}
		if ( preg_match( '/campaign_id IN \(([\d,]+)\)/', $sql, $m ) ) {
			$ids  = array_map( 'intval', explode( ',', $m[1] ) );
			$rows = array_values( array_filter( $rows, fn( $r ) => in_array( (int) $r->campaign_id, $ids, true ) ) );
		}
		if ( strpos( $sql, 'resolved = 0' ) !== false ) {
			$rows = array_values( array_filter( $rows, fn( $r ) => (int) $r->resolved === 0 ) );
		}
		if ( preg_match( '/WHERE id = (\d+)/', $sql, $m ) ) {
			$rows = array_values( array_filter( $rows, fn( $r ) => (int) $r->id === (int) $m[1] ) );
		}
		if ( strpos( $sql, 'ORDER BY month_no' ) !== false ) {
			usort( $rows, fn( $a, $b ) => $a->month_no <=> $b->month_no );
		}
		if ( strpos( $sql, 'ORDER BY sort_order' ) !== false ) {
			usort( $rows, fn( $a, $b ) => $a->sort_order <=> $b->sort_order );
		}
		return $rows;
	}
}

$wpdb = new HarnessWPDB();

require __DIR__ . '/seed_zbrothers.php';   // fills $wpdb->data

// Force a logged-in session without cookies. Declared BEFORE the snippet so the
// snippet's function_exists guard leaves it alone.
function mwm_rm_current_client() {
	global $wpdb;
	return $wpdb->data['wp_mwm_roadmap_clients'][0];
}

require __DIR__ . '/wp-snippet-27-roadmap-portal.php';

$html = call_user_func( $GLOBALS['__sc']['mwm_roadmap_portal'] );

echo "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">";
echo "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">";
echo "<title>Zerlotini Brothers — MWM ROADMAP</title>";
echo "<style>html,body{margin:0;padding:0;background:#fcfcfb}@media(prefers-color-scheme:dark){html,body{background:#1a1a19}}</style>";
echo "</head><body>\n";
echo $html;
echo "\n</body></html>\n";
