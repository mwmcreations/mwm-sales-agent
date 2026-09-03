<?php
/**
 * Plugin Name: MWM Studio Booking
 * Plugin URI: https://mwmcreations.com
 * Description: Self-service studio booking portal for MWM package clients. Manage client hours, bookings, and availability.
 * Version: 2.8.2
 * Author: MWM Creations & Studios
 * Author URI: https://mwmcreations.com
 * License: Proprietary
 * Text Domain: mwm-studio
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit; // No direct access.
}

define( 'MWM_STUDIO_VERSION', '2.8.1' ); // S28: Google Calendar -> portal sync (a drag moves the booking)
define( 'MWM_STUDIO_FILE', __FILE__ );

/**
 * Main plugin class. Everything lives here to keep this a single-file, drop-in plugin.
 */
/**
 * Client-facing time and date formatting.  v2.8.2
 *
 * Michael, 3 Sep 2026, holding a reminder that read "Starting soon — 2026-09-03
 * at 14:15": clients get am/pm.  Times are stored as HH:MM 24-hour and MUST stay
 * that way on the wire — the machine parses start_time/end_time out of the JSON
 * payloads and the calendar sync depends on them.  These two helpers are for
 * WORDS A CLIENT READS, and nothing else.
 *
 * mwm_sb_t12 is deliberately lexical — it does no timezone maths at all.  The
 * stored time is already local studio time, so converting it through a
 * timestamp is a way to be an hour wrong twice a year and never notice.
 */
if ( ! function_exists( 'mwm_sb_t12' ) ) {
	function mwm_sb_t12( $t ) {
		if ( ! preg_match( '/^\s*(\d{1,2}):(\d{2})/', (string) $t, $m ) ) {
			return (string) $t;          // unparseable: show it rather than lose it
		}
		$h  = (int) $m[1];
		$ap = $h >= 12 ? 'PM' : 'AM';
		$h  = $h % 12;
		if ( 0 === $h ) { $h = 12; }
		return $h . ':' . $m[2] . ' ' . $ap;
	}
}
if ( ! function_exists( 'mwm_sb_d12' ) ) {
	function mwm_sb_d12( $d ) {
		$ts = strtotime( (string) $d );
		return $ts ? date_i18n( 'l, F j', $ts ) : (string) $d;
	}
}


class MWM_Studio_Booking {

	/** @var MWM_Studio_Booking */
	private static $instance = null;

	/** @var string */
	private $clients_table;

	/** @var string */
	private $bookings_table;

	/** @var string S26: admin audit trail. */
	private $audit_table;

	/** @var string */
	private $login_attempts_option = 'mwm_studio_login_attempts';

	/** @var string */
	private $settings_option = 'mwm_studio_settings';

	public static function instance() {
		if ( null === self::$instance ) {
			self::$instance = new self();
		}
		return self::$instance;
	}

	private function __construct() {
		global $wpdb;
		$this->clients_table  = $wpdb->prefix . 'mwm_studio_clients';
		$this->bookings_table = $wpdb->prefix . 'mwm_studio_bookings';
		$this->audit_table    = $wpdb->prefix . 'mwm_studio_audit';

		register_activation_hook( MWM_STUDIO_FILE, array( $this, 'activate' ) );

		add_action( 'plugins_loaded', array( $this, 'maybe_upgrade' ) );
		add_action( 'init', array( $this, 'register_shortcode' ) );
		add_action( 'admin_menu', array( $this, 'admin_menu' ) );
		add_action( 'admin_init', array( $this, 'handle_admin_actions' ) );
		add_action( 'admin_enqueue_scripts', array( $this, 'admin_assets' ) );
		add_action( 'wp_enqueue_scripts', array( $this, 'frontend_assets' ) );

		// AJAX handlers - available to logged-out visitors too.
		$ajax_actions = array(
			'mwm_studio_login',
			'mwm_studio_get_dashboard',
			'mwm_studio_get_available_slots',
			'mwm_studio_create_booking',
			'mwm_studio_cancel_booking',
			'mwm_studio_get_history',
			'mwm_studio_logout',
			// S17 (Phase A): public on-demand rental booking.
			'mwm_studio_hold_slot',
			'mwm_studio_confirm_rental',
			'mwm_studio_rental_slots',
			'mwm_studio_rental_month',
			'mwm_studio_manage_get',
			'mwm_studio_manage_cancel',
			'mwm_studio_manage_reschedule',
			// S27: quick-book. No WP session by design; qb_guard() checks token + PIN cookie.
			'mwm_qb_slots',
			'mwm_qb_create',
			// S8.5 (Jul 8 2026): 'mwm_studio_record_calendly_booking' de-registered — portal-only booking; legacy Calendly path had no contract/date/hours checks.
		);
		foreach ( $ajax_actions as $action ) {
			add_action( 'wp_ajax_' . $action, array( $this, $action ) );
			add_action( 'wp_ajax_nopriv_' . $action, array( $this, $action ) );
		}

		// S19c: admin-only QA helpers (capability + nonce checked in handlers).
		add_action( 'wp_ajax_mwm_studio_admin_manage_link', array( $this, 'mwm_studio_admin_manage_link' ) );
		add_action( 'wp_ajax_mwm_studio_admin_qa_confirm', array( $this, 'mwm_studio_admin_qa_confirm' ) );
		add_action( 'wp_ajax_mwm_studio_admin_test_reminder', array( $this, 'mwm_studio_admin_test_reminder' ) );

		// S19c: 24h/2h reminder cron.
		add_action( 'mwm_studio_reminders_event', array( $this, 'run_reminder_cron' ) );
		add_action( 'init', array( $this, 'ensure_reminder_cron' ) );
		add_action( 'init', array( $this, 'ensure_manage_page' ) );
		// S27
		add_action( 'init', array( $this, 'ensure_quick_book_page' ) );
		add_action( 'init', array( $this, 'ensure_drift_cron' ) );
		add_action( 'template_redirect', array( $this, 'qb_handle_gate' ) );
		add_action( 'template_redirect', array( $this, 'qb_maybe_standalone' ), 20 );
		add_action( 'wp_head', array( $this, 'qb_noindex' ) );
		add_action( 'mwm_studio_drift_event', array( $this, 'run_drift_check' ) );

		// S19c: force base64 transfer encoding — the host mail chain QP-decodes 8bit
		// bodies, corrupting '=XX' hex sequences (manage URLs ?b=45&t=<hex> were eaten).
		add_action( 'phpmailer_init', array( $this, 'force_mail_encoding' ) );

		// Auto-complete past bookings opportunistically.
		add_action( 'init', array( $this, 'auto_complete_past_bookings' ) );
		add_action( 'init', array( $this, 'sweep_expired_holds' ) ); // S17
		add_action( 'wp_footer', array( $this, 'rental_bootstrap' ) ); // S17

		// Stripe webhook REST API endpoint.
		add_action( 'rest_api_init', array( $this, 'register_stripe_webhook' ) );

		// S28: Google Calendar -> portal sync (machine calls in; Michael answers a deletion).
		add_action( 'rest_api_init', array( $this, 'register_calendar_sync_route' ) );
		add_action( 'template_redirect', array( $this, 'cal_answer_handler' ) );
	}

	/* =========================================================================
	 * ACTIVATION / SCHEMA
	 * ========================================================================= */

	public function activate() {
		$this->create_tables();
		if ( false === get_option( $this->settings_option ) ) {
			update_option( $this->settings_option, $this->default_settings() );
		}
		update_option( 'mwm_studio_db_version', MWM_STUDIO_VERSION );
	}

	public function maybe_upgrade() {
		if ( get_option( 'mwm_studio_db_version' ) !== MWM_STUDIO_VERSION ) {
			$this->create_tables();
			if ( false === get_option( $this->settings_option ) ) {
				update_option( $this->settings_option, $this->default_settings() );
			}
			update_option( 'mwm_studio_db_version', MWM_STUDIO_VERSION );
		}
	}

	/** S19c: base64-encode outgoing mail (see phpmailer_init hook note). */
	public function force_mail_encoding( $phpmailer ) {
		$phpmailer->Encoding = 'base64';
	}

	/** S19c: create the public /manage-booking/ page (idempotent; runs on init —
	 *  wp_insert_post needs $wp_rewrite, which does not exist at plugins_loaded). */
	public function ensure_manage_page() {
		$known = (int) get_option( 'mwm_studio_manage_page_id' );
		if ( $known && get_post( $known ) ) {
			return;
		}
		$existing = get_page_by_path( 'manage-booking' );
		if ( $existing ) {
			update_option( 'mwm_studio_manage_page_id', $existing->ID );
			return;
		}
		$pid = wp_insert_post( array(
			'post_title'   => 'Manage Your Booking',
			'post_name'    => 'manage-booking',
			'post_type'    => 'page',
			'post_status'  => 'publish',
			'post_content' => '[mwm_manage_booking]',
		) );
		if ( $pid && ! is_wp_error( $pid ) ) {
			update_option( 'mwm_studio_manage_page_id', $pid );
		}
	}

	private function create_tables() {
		global $wpdb;
		$charset_collate = $wpdb->get_charset_collate();

		require_once ABSPATH . 'wp-admin/includes/upgrade.php';

		$sql_clients = "CREATE TABLE {$this->clients_table} (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			name VARCHAR(191) NOT NULL,
			email VARCHAR(191) NOT NULL,
			phone VARCHAR(50) NULL,
			company VARCHAR(191) NULL,
			access_code VARCHAR(255) NOT NULL,
			monthly_hours DECIMAL(5,2) NOT NULL DEFAULT 4.00,
			contract_hours DECIMAL(5,2) NOT NULL DEFAULT 12.00,
			contract_start_date DATE NULL,
			contract_end_date DATE NULL,
			package_name VARCHAR(191) NULL,
			active TINYINT(1) NOT NULL DEFAULT 1,
			notes LONGTEXT NULL,
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
			PRIMARY KEY (id),
			UNIQUE KEY email (email)
		) {$charset_collate};";

		$sql_bookings = "CREATE TABLE {$this->bookings_table} (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			client_id BIGINT UNSIGNED NOT NULL,
			booking_date DATE NOT NULL,
			start_time TIME NOT NULL,
			end_time TIME NOT NULL,
			duration_hours DECIMAL(4,2) NOT NULL,
			status VARCHAR(20) NOT NULL DEFAULT 'confirmed',
			notes LONGTEXT NULL,
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			cancelled_at DATETIME NULL,
			is_rental TINYINT(1) NOT NULL DEFAULT 0,
			guest_name VARCHAR(191) NULL,
			guest_email VARCHAR(191) NULL,
			stripe_session_id VARCHAR(191) NULL,
			amount_cents INT NULL,
			hold_expires_at DATETIME NULL,
			reminder_24_sent TINYINT(1) NOT NULL DEFAULT 0,
			reminder_2_sent TINYINT(1) NOT NULL DEFAULT 0,
			reschedule_count INT NOT NULL DEFAULT 0,
			PRIMARY KEY (id),
			KEY client_id (client_id),
			KEY booking_date (booking_date),
			KEY status (status),
			KEY hold_expires_at (hold_expires_at)
		) {$charset_collate};";

		// S26: audit trail — who changed what, when, and the value it held before.
		$sql_audit = "CREATE TABLE {$this->audit_table} (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			booking_id BIGINT UNSIGNED NULL,
			client_id BIGINT UNSIGNED NULL,
			actor_id BIGINT UNSIGNED NULL,
			actor_name VARCHAR(191) NULL,
			action VARCHAR(40) NOT NULL,
			before_json LONGTEXT NULL,
			after_json LONGTEXT NULL,
			reason VARCHAR(255) NULL,
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			PRIMARY KEY (id),
			KEY booking_id (booking_id),
			KEY client_id (client_id),
			KEY created_at (created_at)
		) {$charset_collate};";

		dbDelta( $sql_clients );
		dbDelta( $sql_bookings );
		dbDelta( $sql_audit );
	}

	private function default_settings() {
		return array(
			'studio_name'          => 'MWM Studio',
			'studio_address'       => '1500 Park Center Dr, Orlando FL 32835, Second Floor',
			'hours'                => array(
				'monday'    => array( 'open' => '09:00', 'close' => '18:00', 'closed' => 0 ),
				'tuesday'   => array( 'open' => '09:00', 'close' => '18:00', 'closed' => 0 ),
				'wednesday' => array( 'open' => '09:00', 'close' => '18:00', 'closed' => 0 ),
				'thursday'  => array( 'open' => '09:00', 'close' => '18:00', 'closed' => 0 ),
				'friday'    => array( 'open' => '09:00', 'close' => '18:00', 'closed' => 0 ),
				'saturday'  => array( 'open' => '10:00', 'close' => '15:00', 'closed' => 0 ),
				'sunday'    => array( 'open' => '10:00', 'close' => '15:00', 'closed' => 1 ),
			),
			'min_booking_hours'    => 1,
			'max_advance_days'     => 30,
			'cancellation_hours'   => 24,
			'buffer_minutes'       => 30,
			'stripe_webhook_secret'     => '',
			'stripe_package_product_id' => 'prod_Uge4IVGqdBNeuR',
			'stripe_contract_hours'     => 12,
			'stripe_contract_months'    => 3,
		);
	}

	private function get_settings() {
		$settings = get_option( $this->settings_option, array() );
		return wp_parse_args( $settings, $this->default_settings() );
	}

	/* =========================================================================
	 * SHORTCODE + FRONTEND ASSETS
	 * ========================================================================= */

	public function register_shortcode() {
		add_shortcode( 'mwm_studio_portal', array( $this, 'render_portal' ) );
		add_shortcode( 'mwm_manage_booking', array( $this, 'render_manage_page' ) );
		add_shortcode( 'mwm_quick_book', array( $this, 'render_quick_book' ) ); // S27
	}

	public function frontend_assets() {
		// Only load jQuery globally; CSS/JS for the portal are inline within the shortcode
		// output so the plugin works as a true drop-in single file with no enqueue misses.
		wp_enqueue_script( 'jquery' );
	}

	public function admin_assets( $hook ) {
		if ( strpos( $hook, 'mwm-studio' ) === false ) {
			return;
		}
		wp_enqueue_style( 'wp-color-picker' );
		wp_enqueue_script( 'wp-color-picker' );
	}

	public function render_portal( $atts = array() ) {
		ob_start();
		$this->render_portal_html();
		return ob_get_clean();
	}

	/* =========================================================================
	 * SESSION / TOKEN HELPERS
	 * ========================================================================= */

	private function transient_key( $token ) {
		return 'mwm_studio_session_' . md5( $token );
	}

	private function create_session( $client_id ) {
		$token = wp_generate_password( 40, false, false );
		set_transient( $this->transient_key( $token ), (int) $client_id, 8 * HOUR_IN_SECONDS );
		return $token;
	}

	private function get_client_id_from_token( $token ) {
		if ( empty( $token ) ) {
			return 0;
		}
		$client_id = get_transient( $this->transient_key( $token ) );
		if ( false === $client_id ) {
			return 0;
		}
		return (int) $client_id;
	}

	private function destroy_session( $token ) {
		delete_transient( $this->transient_key( $token ) );
	}

	private function require_valid_nonce() {
		$nonce = isset( $_POST['nonce'] ) ? sanitize_text_field( wp_unslash( $_POST['nonce'] ) ) : '';
		if ( ! wp_verify_nonce( $nonce, 'mwm_studio_nonce' ) ) {
			wp_send_json_error( array( 'message' => __( 'Security check failed. Please refresh the page and try again.', 'mwm-studio' ) ), 403 );
		}
	}

	private function authenticate_request() {
		$this->require_valid_nonce();
		$token     = isset( $_POST['token'] ) ? sanitize_text_field( wp_unslash( $_POST['token'] ) ) : '';
		$client_id = $this->get_client_id_from_token( $token );
		if ( ! $client_id ) {
			wp_send_json_error( array( 'message' => __( 'Your session has expired. Please log in again.', 'mwm-studio' ), 'code' => 'session_expired' ), 401 );
		}
		$client = $this->get_client( $client_id );
		if ( ! $client || ! $client->active ) {
			wp_send_json_error( array( 'message' => __( 'This account is no longer active.', 'mwm-studio' ) ), 403 );
		}
		return $client;
	}

	/* =========================================================================
	 * RATE LIMITING
	 * ========================================================================= */

	private function is_rate_limited( $email ) {
		$attempts = get_transient( 'mwm_studio_attempts_' . md5( strtolower( $email ) ) );
		return is_array( $attempts ) && count( $attempts ) >= 5;
	}

	private function record_login_attempt( $email ) {
		$key      = 'mwm_studio_attempts_' . md5( strtolower( $email ) );
		$attempts = get_transient( $key );
		if ( ! is_array( $attempts ) ) {
			$attempts = array();
		}
		$attempts[] = time();
		set_transient( $key, $attempts, 15 * MINUTE_IN_SECONDS );
	}

	private function clear_login_attempts( $email ) {
		delete_transient( 'mwm_studio_attempts_' . md5( strtolower( $email ) ) );
	}

	/* =========================================================================
	 * DATA ACCESS HELPERS
	 * ========================================================================= */

	private function get_client( $client_id ) {
		global $wpdb;
		return $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->clients_table} WHERE id = %d", $client_id ) );
	}

	private function get_client_by_email( $email ) {
		global $wpdb;
		return $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->clients_table} WHERE email = %s", $email ) );
	}

	/**
	 * Calculate hours used within the client's contract period.
	 * Contract = 12 hours total across 3 months from first payment date.
	 * Falls back to monthly tracking if no contract dates are set.
	 */
	private function hours_used_in_contract( $client_id, $contract_start = null, $contract_end = null ) {
		global $wpdb;

		if ( $contract_start && $contract_end ) {
			$total = $wpdb->get_var(
				$wpdb->prepare(
					"SELECT COALESCE(SUM(duration_hours),0) FROM {$this->bookings_table}
					WHERE client_id = %d AND status IN ('confirmed','completed','cancelled_late')
					AND booking_date >= %s AND booking_date <= %s",
					$client_id,
					$contract_start,
					$contract_end
				)
			);
		} else {
			// Fallback: sum ALL confirmed/completed bookings (no contract dates set)
			$total = $wpdb->get_var(
				$wpdb->prepare(
					"SELECT COALESCE(SUM(duration_hours),0) FROM {$this->bookings_table}
					WHERE client_id = %d AND status IN ('confirmed','completed','cancelled_late')",
					$client_id
				)
			);
		}
		return (float) $total;
	}

	/**
	 * Legacy wrapper for admin dashboard — counts hours in current month.
	 */
	private function hours_used_this_month( $client_id, $year = null, $month = null ) {
		global $wpdb;
		$year  = $year ? (int) $year : (int) current_time( 'Y' );
		$month = $month ? (int) $month : (int) current_time( 'n' );

		$total = $wpdb->get_var(
			$wpdb->prepare(
				"SELECT COALESCE(SUM(duration_hours),0) FROM {$this->bookings_table}
				WHERE client_id = %d AND status IN ('confirmed','completed','cancelled_late')
				AND YEAR(booking_date) = %d AND MONTH(booking_date) = %d",
				$client_id,
				$year,
				$month
			)
		);
		return (float) $total;
	}

	/**
	 * Get contract status for a client.
	 * Returns 'active', 'expired', or 'no_contract'.
	 */
	private function get_contract_status( $client ) {
		if ( empty( $client->contract_start_date ) || empty( $client->contract_end_date ) ) {
			return 'no_contract';
		}
		$today = current_time( 'Y-m-d' );
		if ( $today > $client->contract_end_date ) {
			return 'expired';
		}
		return 'active';
	}

	private function generate_access_code() {
		$chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // no ambiguous chars
		$code  = '';
		for ( $i = 0; $i < 6; $i++ ) {
			$code .= $chars[ wp_rand( 0, strlen( $chars ) - 1 ) ];
		}
		return $code;
	}

	private function day_key_for_date( $date_str ) {
		$days = array( 'sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday' );
		$ts   = strtotime( $date_str );
		return $days[ (int) date( 'w', $ts ) ];
	}

	/**
	 * Build available time slots (as ["HH:MM","HH:MM+duration"] windows) for a given date & duration.
	 * Returns array of start times (H:i) that can accommodate $duration_hours before close/next booking,
	 * respecting the buffer between bookings.
	 */
	/**
	 * S15: busy blocks from the MWM CREATIONS Google Calendar via the machine's
	 * /studio-availability endpoint, so portal slots respect calendar-only
	 * commitments (shoots, meetings, holds). Returns array of blocks
	 * [['start'=>'HH:MM','end'=>'HH:MM'],...] on success, or NULL when availability
	 * is UNKNOWN (machine unreachable + no usable cache) — callers treat NULL as
	 * fail-closed. Cache ladder (Michael-approved Jul 10 2026): fresh transient
	 * (<5 min) -> live fetch -> stale transient (<=1 h) -> NULL + throttled alert.
	 */
	private function get_gcal_busy_blocks( $date ) {
		static $request_cache = array();
		if ( array_key_exists( $date, $request_cache ) ) {
			return $request_cache[ $date ];
		}

		$transient_key = 'mwm_gcal_busy_' . $date;
		$cached        = get_transient( $transient_key );
		if ( is_array( $cached ) && isset( $cached['blocks'], $cached['fetched'] ) && ( time() - (int) $cached['fetched'] ) < 5 * MINUTE_IN_SECONDS ) {
			$request_cache[ $date ] = $cached['blocks'];
			return $cached['blocks'];
		}

		$base   = get_option( 'mwm_studio_availability_url', 'https://mwm-sales-agent-production.up.railway.app/studio-availability' );
		$secret = get_option( 'mwm_portal_provision_secret' );
		$blocks = null;
		if ( $secret ) {
			// S25d: fetch a 14-day range in ONE machine call (one Google query server-side)
			// and warm the per-date transients, so subsequent date clicks skip the network.
			$resp = wp_remote_get(
				add_query_arg( array( 'date' => rawurlencode( $date ), 'days' => 14 ), $base ),
				array(
					'timeout' => 5,
					'headers' => array( 'X-MWM-Portal-Secret' => $secret ),
				)
			);
			if ( ! is_wp_error( $resp ) && 200 === (int) wp_remote_retrieve_response_code( $resp ) ) {
				$body = json_decode( wp_remote_retrieve_body( $resp ), true );
				if ( is_array( $body ) && isset( $body['busy_by_date'] ) && is_array( $body['busy_by_date'] ) ) {
					$now = time();
					foreach ( $body['busy_by_date'] as $day => $day_busy ) {
						if ( ! is_string( $day ) || ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', $day ) || ! is_array( $day_busy ) ) {
							continue;
						}
						$day_blocks = array();
						foreach ( $day_busy as $b ) {
							if ( isset( $b['start'], $b['end'] ) ) {
								$day_blocks[] = array( 'start' => $b['start'], 'end' => $b['end'] );
							}
						}
						set_transient( 'mwm_gcal_busy_' . $day, array( 'blocks' => $day_blocks, 'fetched' => $now ), HOUR_IN_SECONDS );
						$request_cache[ $day ] = $day_blocks;
						if ( $day === $date ) {
							$blocks = $day_blocks;
						}
					}
				} elseif ( is_array( $body ) && isset( $body['busy'] ) && is_array( $body['busy'] ) ) {
					// Legacy single-day shape (machine not yet on S25d) — unchanged behavior.
					$blocks = array();
					foreach ( $body['busy'] as $b ) {
						if ( isset( $b['start'], $b['end'] ) ) {
							$blocks[] = array( 'start' => $b['start'], 'end' => $b['end'] );
						}
					}
				}
			}
		}

		if ( is_array( $blocks ) ) {
			set_transient( $transient_key, array( 'blocks' => $blocks, 'fetched' => time() ), HOUR_IN_SECONDS );
			$request_cache[ $date ] = $blocks;
			return $blocks;
		}

		// Machine unreachable/bad response: degrade to stale cache (<=1h via transient TTL).
		if ( is_array( $cached ) && isset( $cached['blocks'] ) ) {
			$this->alert_gcal_outage( 'degraded-stale-cache', $date );
			$request_cache[ $date ] = $cached['blocks'];
			return $cached['blocks'];
		}

		// No cache at all: FAIL-CLOSED — availability unknown, hide slots.
		$this->alert_gcal_outage( 'fail-closed', $date );
		$request_cache[ $date ] = null;
		return null;
	}

	/**
	 * S29: a logged-in client was refused every slot for a STRUCTURAL reason —
	 * contract window, expiry, or no hours left. The availability feed already
	 * alerts when it dies; these three branches alerted nothing at all, so a
	 * client could sit in front of an empty calendar for weeks and the only way
	 * we found out was if she happened to email. Throttled once per client per
	 * reason per day.
	 */
	private function notice_client_blocked( $client, $reason, $date, $detail = '' ) {
		if ( empty( $client ) || empty( $client->id ) ) {
			return;
		}
		$key = 'mwm_blocked_' . (int) $client->id . '_' . $reason;
		if ( get_transient( $key ) ) {
			return;
		}
		set_transient( $key, 1, DAY_IN_SECONDS );
		$labels = array(
			'out_of_range'     => 'tried to book past the end of their contract window',
			'contract_expired' => 'has an expired contract and cannot book',
			'no_hours'         => 'has no bookable hours left',
		);
		$what = isset( $labels[ $reason ] ) ? $labels[ $reason ] : $reason;
		wp_mail(
			'michael@mwmcreations.com',
			'[MWM Portal] ' . $client->name . ' cannot book — ' . $reason,
			$client->name . ' (' . $client->email . ') ' . $what . ".\n\n" .
			"Date they asked for: {$date}\n" .
			"Limit: {$detail}\n\n" .
			"They are seeing an empty calendar right now. If this is wrong, fix the client\n" .
			"record; if it is right, they need a human, not a booking page.\n\n" .
			"Throttled to once per client per reason per day."
		);
	}

	/** S15: throttled (1/hr) email alert when the availability feed is degraded or down. */
	private function alert_gcal_outage( $mode, $date ) {
		if ( get_transient( 'mwm_gcal_outage_alerted' ) ) {
			return;
		}
		set_transient( 'mwm_gcal_outage_alerted', 1, HOUR_IN_SECONDS );
		wp_mail(
			'michael@mwmcreations.com',
			'[MWM Portal] Availability feed ' . ( 'fail-closed' === $mode ? 'DOWN - bookings hidden' : 'degraded (stale cache in use)' ),
			"The studio portal could not reach the machine's /studio-availability endpoint (date requested: {$date}).\n\n" .
			"Mode: {$mode}\n" .
			( 'fail-closed' === $mode
				? "Effect: clients see 'booking temporarily unavailable' until the machine responds again.\n"
				: "Effect: slots are filtered with calendar data up to 1 hour old.\n" ) .
			"Check Railway (mwm-sales-agent) status. This alert is throttled to once per hour."
		);
	}

	private function get_available_slots( $date, $duration_hours = null ) {
		global $wpdb;
		$settings = $this->get_settings();
		$day_key  = $this->day_key_for_date( $date );
		$day_conf = isset( $settings['hours'][ $day_key ] ) ? $settings['hours'][ $day_key ] : null;

		if ( ! $day_conf || ! empty( $day_conf['closed'] ) ) {
			return array();
		}

		$open  = $day_conf['open'];
		$close = $day_conf['close'];

		$open_ts  = strtotime( $date . ' ' . $open );
		$close_ts = strtotime( $date . ' ' . $close );

		if ( ! $open_ts || ! $close_ts || $open_ts >= $close_ts ) {
			return array();
		}

		// Don't allow booking in the past (for today).
		$now_ts = current_time( 'timestamp' );
		if ( $open_ts < $now_ts && date( 'Y-m-d', $now_ts ) === $date ) {
			// round up to next hour
			$open_ts = strtotime( date( 'Y-m-d H:00:00', $now_ts + HOUR_IN_SECONDS ) );
		} elseif ( $open_ts < $now_ts && $now_ts > $close_ts ) {
			return array();
		}

		$buffer_seconds = (int) $settings['buffer_minutes'] * 60;

		// Fetch existing confirmed bookings for that date.
		// S17: confirmed bookings AND un-expired rental holds both block a slot.
		// Without the hold clause two customers can pay for the same time.
		// S25d: memoize per request — the duration loop calls this up to 4x per slot.
		static $bookings_memo = array();
		if ( ! array_key_exists( $date, $bookings_memo ) ) {
			$bookings_memo[ $date ] = $wpdb->get_results(
				$wpdb->prepare(
					"SELECT start_time, end_time FROM {$this->bookings_table}
					WHERE booking_date = %s
					  AND ( status = 'confirmed'
					        OR ( status = 'pending_payment' AND hold_expires_at IS NOT NULL AND hold_expires_at > UTC_TIMESTAMP() ) )
					ORDER BY start_time ASC",
					$date
				)
			);
		}
		$bookings = $bookings_memo[ $date ];

		$busy = array();
		foreach ( $bookings as $b ) {
			$b_start = strtotime( $date . ' ' . $b->start_time ) - $buffer_seconds;
			$b_end   = strtotime( $date . ' ' . $b->end_time ) + $buffer_seconds;
			$busy[]  = array( $b_start, $b_end );
		}

		// S15: merge Google Calendar busy blocks so calendar-only commitments
		// block portal slots. NULL = availability unknown -> fail-closed.
		$gcal_blocks = $this->get_gcal_busy_blocks( $date );
		if ( null === $gcal_blocks ) {
			return null;
		}
		foreach ( $gcal_blocks as $g ) {
			$g_start = strtotime( $date . ' ' . $g['start'] );
			$g_end   = strtotime( $date . ' ' . $g['end'] );
			if ( $g_start && $g_end && $g_end > $g_start ) {
				$busy[] = array( $g_start - $buffer_seconds, $g_end + $buffer_seconds );
			}
		}

		$duration_seconds = $duration_hours ? ( (float) $duration_hours * HOUR_IN_SECONDS ) : HOUR_IN_SECONDS;

		$slots = array();
		for ( $slot_start = $open_ts; $slot_start + $duration_seconds <= $close_ts; $slot_start += HOUR_IN_SECONDS ) {
			$slot_end   = $slot_start + $duration_seconds;
			$conflicts  = false;
			foreach ( $busy as $b ) {
				if ( $slot_start < $b[1] && $slot_end > $b[0] ) {
					$conflicts = true;
					break;
				}
			}
			if ( ! $conflicts ) {
				$slots[] = date( 'H:i', $slot_start );
			}
		}

		return $slots;
	}

	/**
	 * Returns max duration (in whole hours, up to 4) that could start at a given start time on a date.
	 */
	private function max_duration_at_slot( $date, $start_time, $cap = 4 ) {
		for ( $d = $cap; $d >= 1; $d-- ) {
			$slots = $this->get_available_slots( $date, $d );
			if ( is_array( $slots ) && in_array( $start_time, $slots, true ) ) {
				return $d;
			}
		}
		return 0;
	}

	public function auto_complete_past_bookings() {
		// Throttle to run at most once every 10 minutes via transient lock.
		if ( get_transient( 'mwm_studio_autocomplete_lock' ) ) {
			return;
		}
		set_transient( 'mwm_studio_autocomplete_lock', 1, 10 * MINUTE_IN_SECONDS );

		global $wpdb;
		$now = current_time( 'mysql' );
		$wpdb->query(
			$wpdb->prepare(
				"UPDATE {$this->bookings_table} SET status = 'completed'
				WHERE status = 'confirmed' AND TIMESTAMP(booking_date, end_time) < %s",
				$now
			)
		);
	}

	private function notify_admin( $subject, $message ) {
		$to = get_option( 'admin_email' );
		wp_mail( $to, $subject, $message );
	}

	/* =========================================================================
	 * AJAX: LOGIN
	 * ========================================================================= */

	private function notify_client( $email, $subject, $message ) {
		if ( ! $email || ! is_email( $email ) ) {
			return;
		}
		wp_mail( $email, $subject, $message );
	}

	private function notify_client_html( $email, $subject, $html ) {
		if ( ! $email || ! is_email( $email ) ) {
			return;
		}
		$headers = array(
			'Content-Type: text/html; charset=UTF-8',
			'From: MWM Creations & Studios <info@mwmcreations.com>',
			'Reply-To: MWM Creations & Studios <michael@mwmcreations.com>',
		);
		wp_mail( $email, $subject, $html, $headers );
	}

	/**
	 * S19: shared branded transactional email shell (gold-on-white, table layout,
	 * inline CSS — Gmail/Outlook safe). Keys: eyebrow, title, preheader, name,
	 * intro, rows (label => value), body_after, cta_label, cta_url, outro.
	 * intro/body_after accept trusted inline HTML (<strong>); escape any dynamic
	 * values interpolated into them. All other values are escaped here.
	 */
	private function get_branded_email_html( $args ) {
		$defaults = array(
			'eyebrow'    => '',
			'title'      => '',
			'preheader'  => '',
			'name'       => '',
			'intro'      => '',
			'rows'       => array(),
			'body_after' => '',
			'cta_label'  => '',
			'cta_url'    => '',
			'outro'      => '',
		);
		$a = array_merge( $defaults, is_array( $args ) ? $args : array() );

		$rows_html = '';
		if ( ! empty( $a['rows'] ) && is_array( $a['rows'] ) ) {
			$inner = '';
			foreach ( $a['rows'] as $mwm_label => $mwm_value ) {
				$inner .= '<tr><td width="112" style="font-size:12px;color:#8b7d3c;font-weight:700;letter-spacing:1px;text-transform:uppercase;vertical-align:top;padding:8px 0;">' . esc_html( $mwm_label ) . '</td><td style="font-size:15px;color:#1a1a2e;font-weight:600;line-height:1.5;padding:8px 0;">' . esc_html( $mwm_value ) . '</td></tr>';
			}
			$rows_html = '<tr><td style="padding:22px 40px 4px;"><table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background-color:#faf6eb;border-radius:10px;border:1px solid #e8ddb5;"><tr><td style="padding:22px 28px;"><table role="presentation" cellpadding="0" cellspacing="0" width="100%">' . $inner . '</table></td></tr></table></td></tr>';
		}

		$cta_html = '';
		if ( $a['cta_label'] && $a['cta_url'] ) {
			$cta_html = '<tr><td align="center" style="padding:26px 40px 6px;"><table role="presentation" cellpadding="0" cellspacing="0"><tr><td align="center" bgcolor="#c9a84c" style="background-color:#c9a84c;border-radius:8px;"><a href="' . esc_url( $a['cta_url'] ) . '" target="_blank" style="display:inline-block;padding:15px 46px;font-size:15px;font-weight:700;color:#1a1a2e;text-decoration:none;letter-spacing:1px;">' . esc_html( $a['cta_label'] ) . '</a></td></tr></table></td></tr>';
		}

		$greeting_html = '';
		if ( $a['name'] ) {
			$greeting_html = '<div style="font-size:17px;color:#1a1a2e;font-weight:600;">Hi ' . esc_html( $a['name'] ) . ',</div>';
		}

		$intro_html = '';
		if ( $a['intro'] ) {
			$intro_html = '<div style="font-size:15px;color:#444444;line-height:1.7;margin-top:12px;">' . $a['intro'] . '</div>';
		}

		$body_after_html = '';
		if ( $a['body_after'] ) {
			$body_after_html = '<tr><td style="padding:20px 40px 0;"><div style="font-size:14px;color:#555555;line-height:1.7;">' . $a['body_after'] . '</div></td></tr>';
		}

		$outro_html = '';
		if ( $a['outro'] ) {
			$outro_html = '<div style="font-size:15px;color:#444444;line-height:1.7;margin-bottom:14px;">' . esc_html( $a['outro'] ) . '</div>';
		}

		return '<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width = device-width, initial-scale = 1.0"><title>' . esc_html( $a['title'] ) . '</title></head>
<body style="margin:0;padding:0;background-color:#f4f4f4;font-family:Arial,\'Helvetica Neue\',Helvetica,sans-serif;">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">' . esc_html( $a['preheader'] ) . '</div>
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background-color:#f4f4f4;">
<tr><td align="center" style="padding:20px 10px;">
<table role="presentation" cellpadding="0" cellspacing="0" width="600" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);">
<tr><td style="padding:36px 40px 22px;text-align:center;border-bottom:1px solid #f0e9d2;">
  <div style="font-size:28px;font-weight:700;color:#1a1a2e;letter-spacing:2px;font-family:Georgia,serif;">MWM CREATIONS</div>
  <div style="font-size:12px;color:#c9a84c;letter-spacing:4px;text-transform:uppercase;margin-top:4px;">&amp; Studios</div>
  <table role="presentation" cellpadding="0" cellspacing="0" width="70" style="margin:16px auto 0;"><tr><td style="height:2px;background-color:#c9a84c;"></td></tr></table>
</td></tr>
<tr><td style="padding:28px 40px 0;text-align:center;">
  <div style="font-size:12px;color:#c9a84c;letter-spacing:3px;text-transform:uppercase;font-weight:700;">' . esc_html( $a['eyebrow'] ) . '</div>
  <div style="font-size:24px;font-weight:700;color:#1a1a2e;margin-top:8px;line-height:1.3;">' . esc_html( $a['title'] ) . '</div>
</td></tr>
<tr><td style="padding:24px 40px 0;">' . $greeting_html . $intro_html . '</td></tr>
' . $rows_html . $body_after_html . $cta_html . '
<tr><td style="padding:24px 40px 30px;">' . $outro_html . '<div style="border-top:2px solid #f0f0f0;padding-top:16px;"><div style="font-size:16px;font-weight:700;color:#1a1a2e;">MWM Creations &amp; Studios</div>
  <div style="font-size:14px;color:#666666;">Orlando, FL</div>
  <div style="font-size:14px;margin-top:4px;"><a href="mailto:info@mwmcreations.com" style="color:#0f3460;text-decoration:none;">info@mwmcreations.com</a></div>
  <div style="font-size:14px;"><a href="https://mwmcreations.com" style="color:#0f3460;text-decoration:none;">mwmcreations.com</a></div></div>
</td></tr>
<tr><td style="background-color:#faf6eb;padding:16px 40px;text-align:center;border-top:1px solid #f0e9d2;">
  <div style="font-size:12px;color:#8b7d3c;">&copy; ' . esc_html( date_i18n( 'Y' ) ) . ' MWM Creations &amp; Studios &middot; Orlando, FL</div>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>';
	}

	private function push_booking_event( $event, $payload ) {
		$url    = get_option( 'mwm_studio_webhook_url', 'https://mwm-sales-agent-production.up.railway.app/webhook/studio-booking' );
		$secret = get_option( 'mwm_portal_provision_secret' );
		if ( ! $url || ! $secret ) {
			return;
		}
		// v2.5.3 (S22 audit gap #1): was fire-and-forget (blocking=false) — a briefly
		// unreachable machine silently lost the calendar sync. Now blocking with
		// verify + one retry + loud admin email on final failure. The machine
		// fast-ACKs this webhook, so blocking costs milliseconds normally.
		$args = array(
			'timeout'  => 5,
			'blocking' => true,
			'headers'  => array(
				'Content-Type'        => 'application/json',
				'X-MWM-Portal-Secret' => $secret,
			),
			'body'     => wp_json_encode( array_merge( array( 'event' => $event, 'sent_at' => gmdate( 'c' ) ), $payload ) ),
		);
		$resp = null;
		for ( $mwm_try = 1; $mwm_try <= 2; $mwm_try++ ) {
			$resp = wp_remote_post( $url, $args );
			if ( ! is_wp_error( $resp ) && 200 === (int) wp_remote_retrieve_response_code( $resp ) ) {
				return;
			}
		}
		$err = is_wp_error( $resp ) ? $resp->get_error_message() : 'HTTP ' . wp_remote_retrieve_response_code( $resp );
		error_log( '[MWM Studio] push_booking_event FAILED (' . $event . '): ' . $err );
		wp_mail(
			get_option( 'admin_email' ),
			'MWM Studio ALERT — calendar sync push FAILED',
			sprintf( "The '%s' event for booking #%s did not reach the machine after 2 attempts (%s).\nThe Google Calendar was NOT updated automatically — please reconcile it by hand.", $event, isset( $payload['booking_id'] ) ? $payload['booking_id'] : '?', $err )
		);
	}

	public function mwm_studio_login() {
		$this->require_valid_nonce();

		$email = isset( $_POST['email'] ) ? sanitize_email( wp_unslash( $_POST['email'] ) ) : '';
		$code  = isset( $_POST['access_code'] ) ? strtoupper( sanitize_text_field( wp_unslash( $_POST['access_code'] ) ) ) : '';

		if ( empty( $email ) || ! is_email( $email ) || empty( $code ) ) {
			wp_send_json_error( array( 'message' => __( 'Please enter a valid email and access code.', 'mwm-studio' ) ) );
		}

		if ( $this->is_rate_limited( $email ) ) {
			wp_send_json_error( array( 'message' => __( 'Too many login attempts. Please try again in 15 minutes.', 'mwm-studio' ) ) );
		}

		$client = $this->get_client_by_email( $email );

		if ( ! $client || ! $client->active || ! wp_check_password( $code, $client->access_code ) ) {
			$this->record_login_attempt( $email );
			wp_send_json_error( array( 'message' => __( 'Invalid email or access code.', 'mwm-studio' ) ) );
		}

		$this->clear_login_attempts( $email );
		$token = $this->create_session( $client->id );

		$settings        = $this->get_settings();
		$contract_hours  = (float) $client->contract_hours;
		$contract_start  = $client->contract_start_date;
		$contract_end    = $client->contract_end_date;
		$contract_status = $this->get_contract_status( $client );
		$used            = $this->hours_used_in_contract( $client->id, $contract_start, $contract_end );
		$remaining       = max( 0, $contract_hours - $used );

		wp_send_json_success(
			array(
				'token'  => $token,
				'client' => array(
					'name'              => $client->name,
					'email'             => $client->email,
					'company'           => $client->company,
					'package_name'      => $client->package_name,
					'contract_hours'    => $contract_hours,
					'hours_used'        => $used,
					'hours_remaining'   => $remaining,
					'contract_start'    => $contract_start,
					'contract_end'      => $contract_end,
					'contract_status'   => $contract_status,
				),
				'studio' => array(
					'name'    => $settings['studio_name'],
					'address' => $settings['studio_address'],
				),
			)
		);
	}

	public function mwm_studio_logout() {
		$this->require_valid_nonce();
		$token = isset( $_POST['token'] ) ? sanitize_text_field( wp_unslash( $_POST['token'] ) ) : '';
		$this->destroy_session( $token );
		wp_send_json_success();
	}

	/* =========================================================================
	 * AJAX: DASHBOARD
	 * ========================================================================= */

	public function mwm_studio_get_dashboard() {
		$client = $this->authenticate_request();
		global $wpdb;

		$contract_hours  = (float) $client->contract_hours;
		$contract_start  = $client->contract_start_date;
		$contract_end    = $client->contract_end_date;
		$contract_status = $this->get_contract_status( $client );
		$used            = $this->hours_used_in_contract( $client->id, $contract_start, $contract_end );
		$remaining       = max( 0, $contract_hours - $used );

		$upcoming = $wpdb->get_results(
			$wpdb->prepare(
				"SELECT * FROM {$this->bookings_table}
				WHERE client_id = %d AND status = 'confirmed'
				AND TIMESTAMP(booking_date, start_time) >= %s
				ORDER BY booking_date ASC, start_time ASC",
				$client->id,
				current_time( 'mysql' )
			)
		);

		$settings = $this->get_settings();
		$cutoff_h = (int) $settings['cancellation_hours'];
		$now_ts   = current_time( 'timestamp' );

		$upcoming_out = array();
		foreach ( $upcoming as $b ) {
			$start_ts        = strtotime( $b->booking_date . ' ' . $b->start_time );
			$hours_until     = ( $start_ts - $now_ts ) / HOUR_IN_SECONDS;
			$upcoming_out[]  = array(
				'id'              => (int) $b->id,
				'date'            => $b->booking_date,
				'date_label'      => date_i18n( 'l, F j, Y', $start_ts ),
				'start_time'      => substr( $b->start_time, 0, 5 ),
				'end_time'        => substr( $b->end_time, 0, 5 ),
				'duration_hours'  => (float) $b->duration_hours,
				'can_cancel'      => $hours_until >= $cutoff_h,
				'notes'           => $b->notes,
			);
		}

		wp_send_json_success(
			array(
				'client' => array(
					'name'              => $client->name,
					'email'             => $client->email,
					'contract_hours'    => $contract_hours,
					'hours_used'        => $used,
					'hours_remaining'   => $remaining,
					'package_name'      => $client->package_name,
					'contract_start'    => $contract_start,
					'contract_end'      => $contract_end,
					'contract_status'   => $contract_status,
				),
				'upcoming' => $upcoming_out,
				'settings' => array(
					'min_booking_hours'  => (float) $settings['min_booking_hours'],
					'max_advance_days'   => (int) $settings['max_advance_days'],
					'cancellation_hours' => (int) $settings['cancellation_hours'],
					'studio_name'        => $settings['studio_name'],
					'studio_address'     => $settings['studio_address'],
					'hours'              => $settings['hours'],
				),
			)
		);
	}

	public function mwm_studio_get_history() {
		$client = $this->authenticate_request();
		global $wpdb;

		$rows = $wpdb->get_results(
			$wpdb->prepare(
				"SELECT * FROM {$this->bookings_table}
				WHERE client_id = %d AND (status IN ('completed','cancelled','cancelled_late') OR TIMESTAMP(booking_date, start_time) < %s)
				ORDER BY booking_date DESC, start_time DESC
				LIMIT 100",
				$client->id,
				current_time( 'mysql' )
			)
		);

		$out = array();
		foreach ( $rows as $b ) {
			$out[] = array(
				'id'             => (int) $b->id,
				'date'           => $b->booking_date,
				'date_label'     => date_i18n( 'M j, Y', strtotime( $b->booking_date ) ),
				'start_time'     => substr( $b->start_time, 0, 5 ),
				'end_time'       => substr( $b->end_time, 0, 5 ),
				'duration_hours' => (float) $b->duration_hours,
				'status'         => $b->status,
			);
		}

		wp_send_json_success( array( 'history' => $out ) );
	}

	/* =========================================================================
	 * AJAX: AVAILABILITY & BOOKING
	 * ========================================================================= */

	public function mwm_studio_get_available_slots() {
		$client = $this->authenticate_request();
		$settings = $this->get_settings();

		$date = isset( $_POST['date'] ) ? sanitize_text_field( wp_unslash( $_POST['date'] ) ) : '';
		if ( ! $date || ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', $date ) ) {
			wp_send_json_error( array( 'message' => __( 'Invalid date.', 'mwm-studio' ) ) );
		}

		$today = current_time( 'Y-m-d' );
		$max_date = date( 'Y-m-d', strtotime( $today . ' +' . (int) $settings['max_advance_days'] . ' days' ) );
		// S8.5 (Michael, Jul 8 2026): bookings may not be dated past the contract end date (= grace deadline).
		if ( ! empty( $client->contract_end_date ) && $max_date > $client->contract_end_date ) {
			$max_date = $client->contract_end_date;
		}

		if ( $date < $today || $date > $max_date ) {
			// S29: a date the portal will NEVER allow used to render exactly like a
			// date that merely happens to be busy — both produced "try another day".
			// A client shopping dates past her contract end therefore concluded the
			// studio was fully booked and stopped trying. Say which limit was hit.
			$oor_kind = ( $date < $today ) ? 'past' : 'after_contract_end';
			if ( 'after_contract_end' === $oor_kind ) {
				$this->notice_client_blocked( $client, 'out_of_range', $date, $max_date );
			}
			wp_send_json_success( array(
				'slots'    => array(),
				'reason'   => 'out_of_range',
				'kind'     => $oor_kind,
				'max_date' => $max_date,
			) );
		}

		// Check contract status
		$contract_status = $this->get_contract_status( $client );
		if ( $contract_status === 'expired' ) {
			$this->notice_client_blocked( $client, 'contract_expired', $date, $client->contract_end_date );
			wp_send_json_success( array(
				'slots'        => array(),
				'reason'       => 'contract_expired',
				'contract_end' => $client->contract_end_date,
			) );
		}

		$used      = $this->hours_used_in_contract( $client->id, $client->contract_start_date, $client->contract_end_date );
		$remaining = max( 0, (float) $client->contract_hours - $used );

		if ( $remaining < (float) $settings['min_booking_hours'] ) {
			$this->notice_client_blocked( $client, 'no_hours', $date, (string) $remaining );
			wp_send_json_success( array(
				'slots'     => array(),
				'reason'    => 'no_hours',
				'remaining' => $remaining,
			) );
		}

		$max_possible = min( 4, floor( $remaining ) );
		if ( $max_possible < 1 ) {
			$max_possible = 1; // allow partial-hour final bookings if remaining < 1 but >= min
		}

		$base_slots = $this->get_available_slots( $date, 1 );
		if ( null === $base_slots ) {
			// S15 fail-closed: machine unreachable and no cached calendar data.
			wp_send_json_success( array( 'slots' => array(), 'reason' => 'availability_unavailable' ) );
		}

		$slot_data = array();
		foreach ( $base_slots as $start ) {
			$max_dur = 0;
			for ( $d = min( 4, (int) ceil( $remaining ) ); $d >= 1; $d-- ) {
				if ( $d > $remaining + 0.001 ) {
					continue;
				}
				$avail = $this->get_available_slots( $date, $d );
				if ( is_array( $avail ) && in_array( $start, $avail, true ) ) {
					$max_dur = $d;
					break;
				}
			}
			if ( $max_dur > 0 ) {
				$slot_data[] = array(
					'start'        => $start,
					'max_duration' => $max_dur,
				);
			}
		}

		wp_send_json_success(
			array(
				'slots'           => $slot_data,
				'hours_remaining' => $remaining,
			)
		);
	}

	public function mwm_studio_create_booking() {
		$client   = $this->authenticate_request();
		$settings = $this->get_settings();
		global $wpdb;

		$date       = isset( $_POST['date'] ) ? sanitize_text_field( wp_unslash( $_POST['date'] ) ) : '';
		$start_time = isset( $_POST['start_time'] ) ? sanitize_text_field( wp_unslash( $_POST['start_time'] ) ) : '';
		$duration   = isset( $_POST['duration'] ) ? (float) $_POST['duration'] : 0;
		$notes      = isset( $_POST['notes'] ) ? sanitize_textarea_field( wp_unslash( $_POST['notes'] ) ) : '';

		if ( ! $date || ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', $date ) ) {
			wp_send_json_error( array( 'message' => __( 'Invalid date.', 'mwm-studio' ) ) );
		}
		if ( ! $start_time || ! preg_match( '/^\d{2}:\d{2}$/', $start_time ) ) {
			wp_send_json_error( array( 'message' => __( 'Invalid start time.', 'mwm-studio' ) ) );
		}
		if ( $duration < (float) $settings['min_booking_hours'] || $duration > 4 ) {
			wp_send_json_error( array( 'message' => __( 'Invalid duration selected.', 'mwm-studio' ) ) );
		}

		$today    = current_time( 'Y-m-d' );
		$max_date = date( 'Y-m-d', strtotime( $today . ' +' . (int) $settings['max_advance_days'] . ' days' ) );
		// S8.5 (Michael, Jul 8 2026): bookings may not be dated past the contract end date (= grace deadline).
		if ( ! empty( $client->contract_end_date ) && $max_date > $client->contract_end_date ) {
			$max_date = $client->contract_end_date;
		}
		if ( $date < $today || $date > $max_date ) {
			wp_send_json_error( array( 'message' => __( 'That date is outside the allowed booking window.', 'mwm-studio' ) ) );
		}

		// Check contract status.
		$contract_status = $this->get_contract_status( $client );
		if ( $contract_status === 'expired' ) {
			wp_send_json_error( array( 'message' => __( 'Your contract has expired. Please contact us to renew.', 'mwm-studio' ) ) );
		}

		// Check remaining contract hours.
		$used      = $this->hours_used_in_contract( $client->id, $client->contract_start_date, $client->contract_end_date );
		$remaining = max( 0, (float) $client->contract_hours - $used );
		if ( $duration > $remaining + 0.001 ) {
			wp_send_json_error( array( 'message' => __( 'You do not have enough hours remaining in your contract for that duration.', 'mwm-studio' ) ) );
		}

		// Re-validate slot is actually available (race condition guard).
		$available = $this->get_available_slots( $date, $duration );
		if ( null === $available ) {
			// S15 fail-closed: availability unknown -> refuse to guess.
			wp_send_json_error( array( 'message' => __( 'Booking is temporarily unavailable — please try again in a few minutes, or message us on WhatsApp.', 'mwm-studio' ) ) );
		}
		if ( ! in_array( $start_time, $available, true ) ) {
			wp_send_json_error( array( 'message' => __( 'That time slot is no longer available. Please pick another time.', 'mwm-studio' ) ) );
		}

		$end_ts   = strtotime( $date . ' ' . $start_time ) + ( $duration * HOUR_IN_SECONDS );
		$end_time = date( 'H:i:s', $end_ts );

		$inserted = $wpdb->insert(
			$this->bookings_table,
			array(
				'client_id'       => $client->id,
				'booking_date'    => $date,
				'start_time'      => $start_time . ':00',
				'end_time'        => $end_time,
				'duration_hours'  => $duration,
				'status'          => 'confirmed',
				'notes'           => $notes,
				'created_at'      => current_time( 'mysql' ),
			),
			array( '%d', '%s', '%s', '%s', '%f', '%s', '%s', '%s' )
		);

		if ( ! $inserted ) {
			wp_send_json_error( array( 'message' => __( 'Could not create booking. Please try again.', 'mwm-studio' ) ) );
		}

		$booking_id = $wpdb->insert_id;
		$this->clear_rental_day_cache( $date );

		// Notify admin.
		$subject = sprintf( '[%s] New Studio Booking: %s', $settings['studio_name'], $client->name );
		$message = sprintf(
			"A new studio booking has been made.\n\nClient: %s (%s)\nDate: %s\nTime: %s - %s\nDuration: %s hour(s)\n\nView in WP Admin: %s",
			$client->name,
			$client->email,
			date_i18n( 'l, F j, Y', strtotime( $date ) ),
			$start_time,
			substr( $end_time, 0, 5 ),
			$duration,
			admin_url( 'admin.php?page=mwm-studio-bookings' )
		);
		$this->notify_admin( $subject, $message );

		// S12: client confirmation email + machine push (S19: branded HTML)
		$mwm_client_subject = sprintf( 'Booking confirmed — %s at %s | %s', mwm_sb_d12( $date ), mwm_sb_t12( $start_time ), $settings['studio_name'] );
		$mwm_cancel_h       = intval( $settings['cancellation_hours'] );
		$mwm_client_html    = $this->get_branded_email_html( array(
			'eyebrow'    => 'Booking Confirmed',
			'title'      => 'Your Studio Session Is Booked',
			'preheader'  => sprintf( 'Your studio session on %s at %s is confirmed.', date_i18n( 'F j, Y', strtotime( $date ) ), mwm_sb_t12( $start_time ) ),
			'name'       => $client->name,
			'intro'      => 'Great news — your studio session is confirmed. Here are your details:',
			'rows'       => array(
				'Date'     => date_i18n( 'l, F j, Y', strtotime( $date ) ),
				'Time'     => mwm_sb_t12( $start_time ) . ' – ' . mwm_sb_t12( $end_time ),
				'Duration' => $duration . ' hour(s)',
				'Location' => $settings['studio_name'] . ', ' . $settings['studio_address'],
			),
			'body_after' => sprintf( 'This booking appears under <strong>Upcoming Bookings</strong> in your client portal. Plans changed? You can cancel from the portal free of charge up to <strong>%d hours</strong> before your session; cancellations within %d hours forfeit the booked hours per your agreement.', $mwm_cancel_h, $mwm_cancel_h ),
			'cta_label'  => 'Open Your Client Portal',
			'cta_url'    => 'https://mwmcreations.com/studio-portal/',
			'outro'      => 'See you at the studio!',
		) );
		$mwm_ics_bk = (object) array( 'id' => $booking_id, 'booking_date' => $date, 'start_time' => $start_time . ':00', 'end_time' => $end_time, 'is_rental' => 0, 'reschedule_count' => 0, 'guest_email' => '', 'created_at' => '' );
		$this->notify_client_html_ics( $client->email, $mwm_client_subject, $mwm_client_html, $mwm_ics_bk );
		$this->push_booking_event( 'booking_created', array(
			'booking_id'   => $booking_id,
			'client_name'  => $client->name,
			'client_email' => $client->email,
			'date'         => $date,
			'start_time'   => $start_time,
			'end_time'     => substr( $end_time, 0, 5 ),
			'duration'     => $duration,
			'notes'        => $notes,
		) );

		wp_send_json_success(
			array(
				'message' => __( 'Booking confirmed!', 'mwm-studio' ),
				'booking' => array(
					'id'             => $booking_id,
					'date'           => $date,
					'date_label'     => date_i18n( 'l, F j, Y', strtotime( $date ) ),
					'start_time'     => $start_time,
					'end_time'       => substr( $end_time, 0, 5 ),
					'duration_hours' => $duration,
					'studio_name'    => $settings['studio_name'],
					'studio_address' => $settings['studio_address'],
				),
			)
		);
	}


	/**
	 * ─────────────────────────────────────────────────────────────────
	 * S17 — CALENDLY PHASE A: public on-demand studio rentals.
	 * Rentals live in the SAME bookings table as package clients, so the two
	 * can never double-book each other. Rentals use client_id = 0 and carry
	 * guest_* + stripe_* columns. Pricing is NEVER trusted from the browser —
	 * the machine (app.py) is the sole pricing authority.
	 * ─────────────────────────────────────────────────────────────────
	 */

	/**
	 * Expose ajaxurl + nonce to the native booking UI on /book-studio.
	 * That page is a hand-built HTML page (not the plugin shortcode), so it has
	 * neither. URI-guard: is_page() proved unreliable there (S14).
	 */
	public function rental_bootstrap() {
		$uri = isset( $_SERVER['REQUEST_URI'] ) ? sanitize_text_field( wp_unslash( $_SERVER['REQUEST_URI'] ) ) : '';
		if ( false === strpos( $uri, 'book-studio' ) && false === strpos( $uri, 'manage-booking' ) ) {
			return;
		}
		printf(
			'<script>window.MWM_RENTAL = { ajaxurl: %s, nonce: %s };</script>',
			wp_json_encode( admin_url( 'admin-ajax.php' ) ),
			wp_json_encode( wp_create_nonce( 'mwm_studio_rental' ) )
		);
	}

	/** Sweep holds whose payment window elapsed. Frees the slot again. */
	public function sweep_expired_holds() {
		global $wpdb;
		$wpdb->query(
			"UPDATE {$this->bookings_table}
			 SET status = 'hold_expired'
			 WHERE status = 'pending_payment'
			   AND hold_expires_at IS NOT NULL
			   AND hold_expires_at < UTC_TIMESTAMP()"
		);
	}

	/* =========================================================================
	 * S19c: MAGIC-LINK MANAGE PAGE + ICS + REMINDERS
	 * ========================================================================= */

	private function manage_token( $booking ) {
		return hash_hmac( 'sha256', $booking->id . '|' . $booking->guest_email . '|' . $booking->created_at, wp_salt( 'auth' ) );
	}

	private function manage_url( $booking ) {
		return home_url( '/manage-booking/' ) . '?b=' . intval( $booking->id ) . '&t=' . substr( $this->manage_token( $booking ), 0, 32 );
	}

	private function get_booking_by_manage_token() {
		global $wpdb;
		$bid = isset( $_REQUEST['b'] ) ? (int) $_REQUEST['b'] : 0;
		$tok = isset( $_REQUEST['t'] ) ? sanitize_text_field( wp_unslash( $_REQUEST['t'] ) ) : '';
		if ( ! $bid || strlen( $tok ) < 20 ) {
			return null;
		}
		$booking = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->bookings_table} WHERE id = %d AND is_rental = 1", $bid ) );
		if ( ! $booking ) {
			return null;
		}
		if ( ! hash_equals( substr( $this->manage_token( $booking ), 0, 32 ), $tok ) ) {
			return null;
		}
		return $booking;
	}

	/** Machine event id: reschedules need fresh idempotency keys + gcal records. */
	private function event_bid( $booking ) {
		$c = isset( $booking->reschedule_count ) ? (int) $booking->reschedule_count : 0;
		return $c > 0 ? $booking->id . '-r' . $c : (string) $booking->id;
	}

	private function ics_escape( $s ) {
		return str_replace( array( '\\', ';', ',', "\n" ), array( '\\\\', '\;', '\,', '\n' ), $s );
	}

	private function build_booking_ics( $booking, $settings ) {
		$rc      = isset( $booking->reschedule_count ) ? (int) $booking->reschedule_count : 0;
		$uid     = 'mwm-booking-' . $booking->id . '-r' . $rc . '@mwmcreations.com';
		$start   = get_gmt_from_date( $booking->booking_date . ' ' . $booking->start_time, 'Ymd\THis\Z' );
		$end     = get_gmt_from_date( $booking->booking_date . ' ' . $booking->end_time, 'Ymd\THis\Z' );
		$now     = gmdate( 'Ymd\THis\Z' );
		$manage  = ( 1 === (int) $booking->is_rental ) ? $this->manage_url( $booking ) : 'https://mwmcreations.com/studio-portal/';
		$lines   = array(
			'BEGIN:VCALENDAR',
			'VERSION:2.0',
			'PRODID:-//MWM Creations & Studios//Studio Booking//EN',
			'CALSCALE:GREGORIAN',
			'METHOD:PUBLISH',
			'BEGIN:VEVENT',
			'UID:' . $uid,
			'DTSTAMP:' . $now,
			'DTSTART:' . $start,
			'DTEND:' . $end,
			'SUMMARY:' . $this->ics_escape( 'Studio Session — ' . $settings['studio_name'] ),
			'LOCATION:' . $this->ics_escape( $settings['studio_name'] . ', ' . $settings['studio_address'] ),
			'DESCRIPTION:' . $this->ics_escape( 'Your studio session at ' . $settings['studio_name'] . '. Manage: ' . $manage ),
			'STATUS:CONFIRMED',
			'END:VEVENT',
			'END:VCALENDAR',
		);
		return implode( "\r\n", $lines ) . "\r\n";
	}

	/** Branded HTML email + .ics calendar attachment. */
	private function notify_client_html_ics( $email, $subject, $html, $booking ) {
		if ( ! $email || ! is_email( $email ) ) {
			return;
		}
		$settings = $this->get_settings();
		$path     = trailingslashit( get_temp_dir() ) . 'mwm-booking-' . intval( $booking->id ) . '.ics';
		$wrote    = @file_put_contents( $path, $this->build_booking_ics( $booking, $settings ) );
		$headers  = array(
			'Content-Type: text/html; charset=UTF-8',
			'From: MWM Creations & Studios <info@mwmcreations.com>',
			'Reply-To: MWM Creations & Studios <michael@mwmcreations.com>',
		);
		wp_mail( $email, $subject, $html, $headers, $wrote ? array( $path ) : array() );
		if ( $wrote ) {
			@unlink( $path );
		}
	}

	public function mwm_studio_manage_get() {
		check_ajax_referer( 'mwm_studio_rental', 'nonce' );
		$booking = $this->get_booking_by_manage_token();
		if ( ! $booking ) {
			wp_send_json_error( array( 'message' => 'Booking not found. Please use the link from your confirmation email.' ) );
		}
		$settings = $this->get_settings();
		$sess_ts  = strtotime( $booking->booking_date . ' ' . $booking->start_time );
		$gt24     = ( $sess_ts - current_time( 'timestamp' ) ) >= DAY_IN_SECONDS;
		wp_send_json_success( array(
			'status'     => $booking->status,
			'date'       => $booking->booking_date,
			'date_label' => date_i18n( 'l, F j, Y', strtotime( $booking->booking_date ) ),
			'start'      => substr( $booking->start_time, 0, 5 ),
			'end'        => substr( $booking->end_time, 0, 5 ),
			'duration'   => (float) $booking->duration_hours,
			'name'       => $booking->guest_name,
			'amount'     => $booking->amount_cents ? number_format( $booking->amount_cents / 100, 2 ) : '',
			'gt24'       => $gt24,
			'location'   => $settings['studio_name'] . ', ' . $settings['studio_address'],
		) );
	}

	public function mwm_studio_manage_cancel() {
		check_ajax_referer( 'mwm_studio_rental', 'nonce' );
		global $wpdb;
		$booking = $this->get_booking_by_manage_token();
		if ( ! $booking || 'confirmed' !== $booking->status ) {
			wp_send_json_error( array( 'message' => 'This booking is not active, so it cannot be cancelled.' ) );
		}
		$settings = $this->get_settings();
		$sess_ts  = strtotime( $booking->booking_date . ' ' . $booking->start_time );
		$late     = ( $sess_ts - current_time( 'timestamp' ) ) < DAY_IN_SECONDS;
		$wpdb->update(
			$this->bookings_table,
			array( 'status' => $late ? 'cancelled_late' : 'cancelled', 'cancelled_at' => current_time( 'mysql' ) ),
			array( 'id' => $booking->id )
		);
		$this->clear_rental_day_cache( $booking->booking_date );
		$amount       = $booking->amount_cents ? number_format( $booking->amount_cents / 100, 2 ) : '';
		$fee_cents    = $booking->amount_cents ? ( (int) round( (int) $booking->amount_cents * 0.029 ) + 30 ) : 0;
		$refund_cents = $booking->amount_cents ? max( 0, (int) $booking->amount_cents - $fee_cents ) : 0;
		$fee_disp     = number_format( $fee_cents / 100, 2 );
		$refund_disp  = number_format( $refund_cents / 100, 2 );
		$start  = substr( $booking->start_time, 0, 5 );
		$end    = substr( $booking->end_time, 0, 5 );
		if ( $late ) {
			$this->notify_admin(
				sprintf( '[%s] Rental cancelled LATE (<24h, no refund) — #%d %s', $settings['studio_name'], $booking->id, $booking->guest_name ),
				sprintf( "Rental booking #%d cancelled via manage link within 24h of the session.\nGuest: %s (%s)\n%s %s-%s\nNo refund due per policy.", $booking->id, $booking->guest_name, $booking->guest_email, $booking->booking_date, $start, $end )
			);
		} else {
			$this->notify_admin(
				sprintf( '[%s] REFUND NEEDED ~$%s — rental cancelled #%d %s', $settings['studio_name'], $refund_disp, $booking->id, $booking->guest_name ),
				sprintf( "Rental booking #%d cancelled via manage link MORE than 24h ahead — refund due MINUS processing fees.\nGuest: %s (%s)\n%s %s-%s\nAmount paid: $%s\nEst. processing fee (kept by Stripe): $%s\nREFUND DUE: ~$%s — check the exact fee on the payment in Stripe and refund (paid minus fee).\nStripe session: %s\n(Refund automation lands with the real-card session.)", $booking->id, $booking->guest_name, $booking->guest_email, $booking->booking_date, $start, $end, $amount, $fee_disp, $refund_disp, $booking->stripe_session_id )
			);
		}
		$policy = $late
			? 'Because this cancellation was within <strong>24 hours</strong> of the session, the booking is non-refundable per our policy.'
			: 'Your payment' . ( $amount ? ' of <strong>$' . $amount . '</strong>' : '' ) . ' will be refunded minus payment-processing fees' . ( $refund_cents ? ' — a refund of approximately <strong>$' . $refund_disp . '</strong>' : '' ) . ' to your original payment method. Please allow 1–2 business days for it to appear.';
		$html = $this->get_branded_email_html( array(
			'eyebrow'    => 'Booking Cancelled',
			'title'      => 'Your Session Was Cancelled',
			'preheader'  => sprintf( 'Your studio session on %s was cancelled.', date_i18n( 'F j, Y', strtotime( $booking->booking_date ) ) ),
			'name'       => $booking->guest_name,
			'intro'      => 'Your studio session below has been cancelled.',
			'rows'       => array(
				'Date' => date_i18n( 'l, F j, Y', strtotime( $booking->booking_date ) ),
				'Time' => mwm_sb_t12( $start ) . ' – ' . mwm_sb_t12( $end ),
			),
			'body_after' => $policy . ' We would love to see you back — you can book a new session any time.',
			'cta_label'  => 'Book a New Session',
			'cta_url'    => 'https://mwmcreations.com/book-studio/',
			'outro'      => 'Hope to see you back at the studio soon,',
		) );
		$this->notify_client_html( $booking->guest_email, sprintf( 'Booking cancelled — %s at %s | %s', $booking->booking_date, $start, $settings['studio_name'] ), $html );
		$this->push_booking_event( $late ? 'booking_cancelled_late' : 'booking_cancelled', array(
			'booking_id'   => $this->event_bid( $booking ),
			'client_name'  => $booking->guest_name . ' (rental)',
			'client_email' => $booking->guest_email,
			'date'         => $booking->booking_date,
			'start_time'   => $start,
			'end_time'     => $end,
		) );
		wp_send_json_success( array(
			'message' => $late
				? 'Your booking was cancelled. Per policy, bookings cancelled within 24 hours of the session are non-refundable.'
				: 'Your booking was cancelled and your refund (minus payment-processing fees) is on its way — please allow 1–2 business days.',
		) );
	}

	public function mwm_studio_manage_reschedule() {
		check_ajax_referer( 'mwm_studio_rental', 'nonce' );
		global $wpdb;
		$booking = $this->get_booking_by_manage_token();
		if ( ! $booking || 'confirmed' !== $booking->status ) {
			wp_send_json_error( array( 'message' => 'This booking is not active, so it cannot be rescheduled.' ) );
		}
		$sess_ts = strtotime( $booking->booking_date . ' ' . $booking->start_time );
		if ( ( $sess_ts - current_time( 'timestamp' ) ) < DAY_IN_SECONDS ) {
			wp_send_json_error( array( 'message' => 'Within 24 hours of the session, rescheduling is no longer available per our policy.' ) );
		}
		$date  = isset( $_POST['date'] ) ? sanitize_text_field( wp_unslash( $_POST['date'] ) ) : '';
		$start = isset( $_POST['start_time'] ) ? sanitize_text_field( wp_unslash( $_POST['start_time'] ) ) : '';
		if ( ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', $date ) || ! preg_match( '/^\d{2}:\d{2}$/', $start ) ) {
			wp_send_json_error( array( 'message' => 'Invalid date or time.' ) );
		}
		$duration = (float) $booking->duration_hours;
		$slots    = $this->get_available_slots( $date, $duration );
		if ( null === $slots ) {
			wp_send_json_error( array( 'message' => 'Booking is temporarily unavailable. Please message us on WhatsApp and we will get you rescheduled.' ) );
		}
		$found = false;
		foreach ( $slots as $s ) {
			$slot_start = is_array( $s ) ? ( isset( $s['start'] ) ? $s['start'] : '' ) : (string) $s;
			if ( $slot_start === $start ) {
				$found = true;
				break;
			}
		}
		if ( ! $found ) {
			wp_send_json_error( array( 'message' => 'That time was just taken — please pick another slot.' ) );
		}
		$settings  = $this->get_settings();
		$old_label = date_i18n( 'l, F j, Y', strtotime( $booking->booking_date ) ) . ' · ' . mwm_sb_t12( $booking->start_time ) . '–' . mwm_sb_t12( $booking->end_time );
		$old_date  = $booking->booking_date;
		// Remove the OLD calendar event first (old idempotency id).
		$this->push_booking_event( 'booking_cancelled', array(
			'booking_id'   => $this->event_bid( $booking ),
			'client_name'  => $booking->guest_name . ' (rental — rescheduling)',
			'client_email' => $booking->guest_email,
			'date'         => $booking->booking_date,
			'start_time'   => substr( $booking->start_time, 0, 5 ),
			'end_time'     => substr( $booking->end_time, 0, 5 ),
		) );
		$new_end = date( 'H:i:s', strtotime( $date . ' ' . $start . ':00' ) + (int) round( $duration * HOUR_IN_SECONDS ) );
		$wpdb->update(
			$this->bookings_table,
			array(
				'booking_date'     => $date,
				'start_time'       => $start . ':00',
				'end_time'         => $new_end,
				'reschedule_count' => (int) $booking->reschedule_count + 1,
			),
			array( 'id' => $booking->id )
		);
		$this->clear_rental_day_cache( $old_date );
		$this->clear_rental_day_cache( $date );
		$fresh = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->bookings_table} WHERE id = %d", $booking->id ) );
		// Create the NEW calendar event under a fresh idempotency id.
		$this->push_booking_event( 'booking_created', array(
			'booking_id'   => $this->event_bid( $fresh ),
			'client_name'  => $fresh->guest_name . ' (rental — rescheduled)',
			'client_email' => $fresh->guest_email,
			'date'         => $fresh->booking_date,
			'start_time'   => substr( $fresh->start_time, 0, 5 ),
			'end_time'     => substr( $fresh->end_time, 0, 5 ),
			'duration'     => $fresh->duration_hours,
			'notes'        => 'Rescheduled via manage link (was ' . $old_label . ')',
		) );
		$this->notify_admin(
			sprintf( '[%s] Rental RESCHEDULED — #%d %s', $settings['studio_name'], $fresh->id, $fresh->guest_name ),
			sprintf( "Rental booking #%d rescheduled via manage link.\nGuest: %s (%s)\nWas: %s\nNow: %s %s-%s", $fresh->id, $fresh->guest_name, $fresh->guest_email, $old_label, $fresh->booking_date, substr( $fresh->start_time, 0, 5 ), substr( $fresh->end_time, 0, 5 ) )
		);
		$html = $this->get_branded_email_html( array(
			'eyebrow'    => 'Booking Updated',
			'title'      => 'Your Session Was Rescheduled',
			'preheader'  => sprintf( 'Your studio session moved to %s at %s.', date_i18n( 'F j, Y', strtotime( $fresh->booking_date ) ), substr( $fresh->start_time, 0, 5 ) ),
			'name'       => $fresh->guest_name,
			'intro'      => 'All set — your studio session has been moved. Here are your new details:',
			'rows'       => array(
				'New Date' => date_i18n( 'l, F j, Y', strtotime( $fresh->booking_date ) ),
				'New Time' => substr( $fresh->start_time, 0, 5 ) . ' – ' . substr( $fresh->end_time, 0, 5 ),
				'Duration' => $fresh->duration_hours . ' hour(s)',
				'Location' => $settings['studio_name'] . ', ' . $settings['studio_address'],
			),
			'body_after' => 'Previously: ' . esc_html( $old_label ) . '. An updated calendar invite (.ics) is attached. Need another change? Use the button below — free up to <strong>24 hours</strong> before your session.',
			'cta_label'  => 'Manage Your Booking',
			'cta_url'    => $this->manage_url( $fresh ),
			'outro'      => 'See you at the studio!',
		) );
		$this->notify_client_html_ics( $fresh->guest_email, sprintf( 'Booking updated — %s at %s | %s', $fresh->booking_date, substr( $fresh->start_time, 0, 5 ), $settings['studio_name'] ), $html, $fresh );
		wp_send_json_success( array(
			'message'    => 'Your session was rescheduled. A confirmation with an updated calendar invite is on its way.',
			'date_label' => date_i18n( 'l, F j, Y', strtotime( $fresh->booking_date ) ),
			'start'      => substr( $fresh->start_time, 0, 5 ),
			'end'        => substr( $fresh->end_time, 0, 5 ),
		) );
	}

	/* ---- S19c: reminders ---- */

	public function ensure_reminder_cron() {
		if ( ! wp_next_scheduled( 'mwm_studio_reminders_event' ) ) {
			wp_schedule_event( time() + 300, 'hourly', 'mwm_studio_reminders_event' );
		}
	}

	public function run_reminder_cron() {
		global $wpdb;
		$now   = current_time( 'timestamp' );
		$today = date( 'Y-m-d', $now );
		$until = date( 'Y-m-d', $now + 2 * DAY_IN_SECONDS );
		$rows  = $wpdb->get_results( $wpdb->prepare(
			"SELECT * FROM {$this->bookings_table}
			 WHERE status = 'confirmed' AND booking_date >= %s AND booking_date <= %s
			   AND ( reminder_24_sent = 0 OR reminder_2_sent = 0 )",
			$today,
			$until
		) );
		if ( ! $rows ) {
			return;
		}
		foreach ( $rows as $bk ) {
			$start_ts = strtotime( $bk->booking_date . ' ' . $bk->start_time );
			if ( ! $start_ts ) {
				continue;
			}
			$left = $start_ts - $now;
			if ( $left <= 0 ) {
				continue;
			}
			if ( $left <= 2 * HOUR_IN_SECONDS ) {
				if ( ! (int) $bk->reminder_2_sent ) {
					$this->send_booking_reminder( $bk, '2h' );
					$wpdb->update( $this->bookings_table, array( 'reminder_2_sent' => 1, 'reminder_24_sent' => 1 ), array( 'id' => $bk->id ) );
				}
			} elseif ( $left <= 24 * HOUR_IN_SECONDS ) {
				if ( ! (int) $bk->reminder_24_sent ) {
					$this->send_booking_reminder( $bk, '24h' );
					$wpdb->update( $this->bookings_table, array( 'reminder_24_sent' => 1 ), array( 'id' => $bk->id ) );
				}
			}
		}
	}

	private function send_booking_reminder( $booking, $type ) {
		$settings  = $this->get_settings();
		$is_rental = 1 === (int) $booking->is_rental;
		if ( $is_rental ) {
			$email = $booking->guest_email;
			$name  = $booking->guest_name;
		} else {
			$client = $this->get_client( $booking->client_id );
			if ( ! $client ) {
				return;
			}
			$email = $client->email;
			$name  = $client->name;
		}
		$start      = substr( $booking->start_time, 0, 5 );
		$end        = substr( $booking->end_time, 0, 5 );
		$date_label = date_i18n( 'l, F j, Y', strtotime( $booking->booking_date ) );
		$is24       = ( '2h' !== $type );
		$cta_url    = $is_rental ? $this->manage_url( $booking ) : 'https://mwmcreations.com/studio-portal/';
		$cta_label  = $is_rental ? 'Manage Your Booking' : 'Open Your Client Portal';
		if ( $is24 ) {
			$title     = 'Your Session Is Tomorrow';
			$intro     = 'Just a friendly reminder — your studio session is coming up. Here are the details:';
			$preheader = sprintf( 'Reminder: your studio session is tomorrow at %s.', mwm_sb_t12( $start ) );
			$body      = $is_rental
				? 'Need to change plans? Up to <strong>24 hours</strong> before your session you can reschedule free of charge, or cancel for a refund minus payment-processing fees — after that the booking is non-refundable. Please arrive 5–10 minutes early so we can get you set up.'
				: 'Plans changed? You can cancel or rebook from your client portal up to <strong>24 hours</strong> before your session. Please arrive 5–10 minutes early so we can get you set up.';
			$subject   = sprintf( 'Reminder: session tomorrow — %s at %s | %s', mwm_sb_d12( $booking->booking_date ), mwm_sb_t12( $start ), $settings['studio_name'] );
		} else {
			$title     = 'See You Soon!';
			$intro     = 'Your studio session starts in about two hours. Here are the details:';
			$preheader = sprintf( 'Your studio session starts at %s today.', mwm_sb_t12( $start ) );
			$body      = 'Please arrive 5–10 minutes early so we can get you set up. See you shortly!';
			$subject   = sprintf( 'Starting soon — %s at %s | %s', mwm_sb_d12( $booking->booking_date ), mwm_sb_t12( $start ), $settings['studio_name'] );
		}
		$html = $this->get_branded_email_html( array(
			'eyebrow'    => 'Session Reminder',
			'title'      => $title,
			'preheader'  => $preheader,
			'name'       => $name,
			'intro'      => $intro,
			'rows'       => array(
				'Date'     => $date_label,
				'Time'     => mwm_sb_t12( $start ) . ' – ' . mwm_sb_t12( $end ),
				'Duration' => $booking->duration_hours . ' hour(s)',
				'Location' => $settings['studio_name'] . ', ' . $settings['studio_address'],
			),
			'body_after' => $body,
			'cta_label'  => $cta_label,
			'cta_url'    => $cta_url,
			'outro'      => 'See you at the studio!',
		) );
		$this->notify_client_html_ics( $email, $subject, $html, $booking );
	}

	/* ---- S19c: admin QA helpers (temporary; capability + nonce gated) ---- */

	public function mwm_studio_admin_manage_link() {
		check_ajax_referer( 'mwm_studio_rental', 'nonce' );
		if ( ! current_user_can( 'manage_options' ) ) {
			wp_send_json_error( array( 'message' => 'forbidden' ) );
		}
		global $wpdb;
		$bid     = isset( $_POST['booking_id'] ) ? (int) $_POST['booking_id'] : 0;
		$booking = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->bookings_table} WHERE id = %d AND is_rental = 1", $bid ) );
		if ( ! $booking ) {
			wp_send_json_error( array( 'message' => 'not found / not a rental' ) );
		}
		wp_send_json_success( array( 'url' => $this->manage_url( $booking ) ) );
	}

	public function mwm_studio_admin_qa_confirm() {
		check_ajax_referer( 'mwm_studio_rental', 'nonce' );
		if ( ! current_user_can( 'manage_options' ) ) {
			wp_send_json_error( array( 'message' => 'forbidden' ) );
		}
		global $wpdb;
		$bid = isset( $_POST['booking_id'] ) ? (int) $_POST['booking_id'] : 0;
		$booking = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->bookings_table} WHERE id = %d AND is_rental = 1", $bid ) );
		if ( ! $booking ) {
			wp_send_json_error( array( 'message' => 'not found / not a rental' ) );
		}
		$wpdb->update( $this->bookings_table, array( 'status' => 'confirmed', 'hold_expires_at' => null ), array( 'id' => $bid ) );
		$this->clear_rental_day_cache( $booking->booking_date );
		wp_send_json_success( array( 'message' => 'QA: booking confirmed silently (no emails, no machine push).' ) );
	}

	public function mwm_studio_admin_test_reminder() {
		check_ajax_referer( 'mwm_studio_rental', 'nonce' );
		if ( ! current_user_can( 'manage_options' ) ) {
			wp_send_json_error( array( 'message' => 'forbidden' ) );
		}
		global $wpdb;
		$bid  = isset( $_POST['booking_id'] ) ? (int) $_POST['booking_id'] : 0;
		$type = isset( $_POST['type'] ) && '2h' === $_POST['type'] ? '2h' : '24h';
		$booking = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->bookings_table} WHERE id = %d", $bid ) );
		if ( ! $booking ) {
			wp_send_json_error( array( 'message' => 'not found' ) );
		}
		$this->send_booking_reminder( $booking, $type );
		wp_send_json_success( array( 'message' => 'QA: ' . $type . ' reminder sent (flags untouched).' ) );
	}

	/** S19c: /manage-booking/ page (shortcode). Token-gated; JS drives everything. */
	public function render_manage_page() {
		$css = <<<'MWMCSS'
<style>
.mwm-mb-wrap { max-width:640px; margin:40px auto 80px; padding:0 16px; font-family:Arial,'Helvetica Neue',Helvetica,sans-serif; }
.mwm-mb-card { background:#0A0A0A; border:1px solid #2A2A2A; border-radius:14px; padding:32px 28px; color:#FFFFFF; }
.mwm-mb-eyebrow { font-size:12px; color:#C8A96E; letter-spacing:3px; text-transform:uppercase; font-weight:700; text-align:center; }
.mwm-mb-title { font-size:24px; font-weight:700; text-align:center; margin:8px 0 22px; color:#FFFFFF; }
.mwm-mb-rows { background:#111111; border:1px solid #2A2A2A; border-radius:10px; padding:18px 20px; margin-bottom:18px; }
.mwm-mb-row { display:flex; gap:14px; padding:6px 0; font-size:15px; }
.mwm-mb-row b { color:#C8A96E; min-width:100px; font-size:12px; letter-spacing:1px; text-transform:uppercase; padding-top:2px; }
.mwm-mb-status { text-align:center; font-size:14px; color:#B0B0B0; margin-bottom:18px; }
.mwm-mb-actions { display:flex; gap:12px; justify-content:center; flex-wrap:wrap; }
.mwm-mb-btn { border:none; border-radius:8px; padding:14px 28px; font-size:15px; font-weight:700; cursor:pointer; letter-spacing:1px; }
.mwm-mb-btn-gold { background:#C8A96E; color:#111111; }
.mwm-mb-btn-ghost { background:transparent; color:#C8A96E; border:1px solid #C8A96E; }
.mwm-mb-btn:disabled { opacity:.45; cursor:default; }
.mwm-mb-msg { text-align:center; font-size:14px; color:#B0B0B0; margin-top:16px; line-height:1.6; }
.mwm-mb-msg.mwm-mb-ok { color:#C8A96E; }
.mwm-mb-policy { font-size:13px; color:#808080; text-align:center; margin-top:20px; line-height:1.6; }
.mwm-mb-resched { display:none; margin-top:24px; }
.mwm-mb-sub { font-size:13px; color:#C8A96E; letter-spacing:2px; text-transform:uppercase; font-weight:700; margin:18px 0 10px; }
.mwm-mb-cal { background:#111111; border:1px solid #2A2A2A; border-radius:12px; padding:16px; }
.mwm-mb-cal-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; }
.mwm-mb-cal-title { color:#FFFFFF; font-size:15px; font-weight:700; letter-spacing:1px; }
.mwm-mb-cal-nav { background:#1A1A1A; border:1px solid #2A2A2A; color:#C8A96E; width:32px; height:32px; border-radius:8px; font-size:16px; cursor:pointer; line-height:1; }
.mwm-mb-cal-nav:disabled { opacity:.35; cursor:default; }
.mwm-mb-cal-grid { display:grid; grid-template-columns:repeat(7,1fr); gap:5px; }
.mwm-mb-cal-dow { color:#808080; font-size:10px; text-transform:uppercase; letter-spacing:1px; text-align:center; padding:3px 0; }
.mwm-mb-cal-day { background:transparent; border:1px solid transparent; border-radius:7px; color:#4A4A4A; padding:8px 0; font-size:13px; font-weight:600; text-align:center; }
.mwm-mb-cal-day.mwm-mb-avail { background:#1A1A1A; border-color:#3d3420; color:#C8A96E; cursor:pointer; }
.mwm-mb-cal-day.mwm-mb-on { background:#C8A96E; border-color:#C8A96E; color:#111111; }
.mwm-mb-slots { display:grid; grid-template-columns:repeat(auto-fill,minmax(90px,1fr)); gap:8px; margin-top:12px; }
.mwm-mb-slot { background:#111111; border:1px solid #2A2A2A; border-radius:8px; color:#FFFFFF; padding:10px 0; font-size:14px; font-weight:600; cursor:pointer; }
.mwm-mb-slot.mwm-mb-on { background:#C8A96E; border-color:#C8A96E; color:#111111; }
</style>
MWMCSS;
		$shell = '<div class="mwm-mb-wrap"><div class="mwm-mb-card" id="mwm-mb"><div class="mwm-mb-msg">Loading your booking…</div></div></div>';
		$js = <<<'MWMJS'
<script>
(function () {
  function init() {
    var boot = window.MWM_RENTAL || {};
    var root = document.getElementById('mwm-mb');
    if (!root) { return; }
    var qs = new URLSearchParams(window.location.search);
    var B = { b: qs.get('b') || '', t: qs.get('t') || '' };
    var state = null;
    var calY = 0, calM = 0, pickDate = '', pickSlot = '';
    // S24c: display times as 12-hour AM/PM (values stay 24h for the API)
    function fmt12(t) {
      var p = String(t).split(':');
      var h = parseInt(p[0], 10);
      if (isNaN(h)) { return t; }
      return ((h % 12) || 12) + ':' + (p[1] || '00') + ' ' + (h >= 12 ? 'PM' : 'AM');
    }

    function api(action, data, cb) {
      if (!boot.ajaxurl || !boot.nonce) { cb({ success: false, data: { message: 'Page is temporarily unavailable — please refresh.' } }); return; }
      var fd = new FormData();
      fd.append('action', action);
      fd.append('nonce', boot.nonce);
      fd.append('b', B.b);
      fd.append('t', B.t);
      Object.keys(data).forEach(function (k) { fd.append(k, data[k]); });
      fetch(boot.ajaxurl, { method: 'POST', body: fd, credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(cb)
        .catch(function () { cb({ success: false, data: { message: 'Network error — please try again.' } }); });
    }
    function esc(s) { var d = document.createElement('div'); d.textContent = String(s == null ? '' : s); return d.innerHTML; }
    function msg(text, ok) { var el = root.querySelector('.mwm-mb-msg'); if (el) { el.textContent = text; el.className = 'mwm-mb-msg' + (ok ? ' mwm-mb-ok' : ''); } }

    function render() {
      var s = state;
      var statusLabel = { confirmed: 'Confirmed', pending_payment: 'Pending payment', cancelled: 'Cancelled', cancelled_late: 'Cancelled (late)' }[s.status] || s.status;
      var h = '';
      h += '<div class="mwm-mb-eyebrow">Manage Booking</div>';
      h += '<div class="mwm-mb-title">Hi ' + esc(s.name) + ' — your studio session</div>';
      h += '<div class="mwm-mb-rows">';
      h += '<div class="mwm-mb-row"><b>Date</b><span>' + esc(s.date_label) + '</span></div>';
      h += '<div class="mwm-mb-row"><b>Time</b><span>' + esc(s.start) + ' – ' + esc(s.end) + '</span></div>';
      h += '<div class="mwm-mb-row"><b>Duration</b><span>' + esc(s.duration) + ' hour(s)</span></div>';
      if (s.amount) { h += '<div class="mwm-mb-row"><b>Paid</b><span>$' + esc(s.amount) + '</span></div>'; }
      h += '<div class="mwm-mb-row"><b>Location</b><span>' + esc(s.location) + '</span></div>';
      h += '</div>';
      h += '<div class="mwm-mb-status">Status: ' + esc(statusLabel) + '</div>';
      if (s.status === 'confirmed') {
        h += '<div class="mwm-mb-actions">';
        if (s.gt24) { h += '<button type="button" class="mwm-mb-btn mwm-mb-btn-gold" id="mwm-mb-resched-btn">Reschedule</button>'; }
        h += '<button type="button" class="mwm-mb-btn mwm-mb-btn-ghost" id="mwm-mb-cancel-btn">Cancel booking</button>';
        h += '</div>';
        h += '<div class="mwm-mb-resched" id="mwm-mb-resched">';
        h += '<div class="mwm-mb-sub">Pick a new date</div><div class="mwm-mb-cal" id="mwm-mb-cal"></div>';
        h += '<div class="mwm-mb-sub" id="mwm-mb-slots-label" style="display:none">Pick a new start time</div><div class="mwm-mb-slots" id="mwm-mb-slots"></div>';
        h += '<div class="mwm-mb-actions" style="margin-top:16px"><button type="button" class="mwm-mb-btn mwm-mb-btn-gold" id="mwm-mb-confirm-resched" disabled>Confirm new time</button></div>';
        h += '</div>';
        h += s.gt24
          ? '<div class="mwm-mb-policy">Free reschedule until 24 hours before your session; cancellations are refunded minus payment-processing fees.<br>Within 24 hours the booking is non-refundable.</div>'
          : '<div class="mwm-mb-policy">Your session is less than 24 hours away — per policy it is non-refundable and can no longer be rescheduled. You may still cancel below if you cannot make it.</div>';
      }
      h += '<div class="mwm-mb-msg"></div>';
      root.innerHTML = h;
      var cb = document.getElementById('mwm-mb-cancel-btn');
      if (cb) { cb.addEventListener('click', doCancel); }
      var rb = document.getElementById('mwm-mb-resched-btn');
      if (rb) { rb.addEventListener('click', function () { document.getElementById('mwm-mb-resched').style.display = 'block'; rb.disabled = true; calRefresh(); }); }
      var cf = document.getElementById('mwm-mb-confirm-resched');
      if (cf) { cf.addEventListener('click', doResched); }
    }

    function doCancel() {
      var warn = state.gt24
        ? 'Cancel this booking? Your payment will be refunded minus payment-processing fees.'
        : 'Cancel this booking? It is within 24 hours of the session, so per policy it is NON-REFUNDABLE.';
      if (!window.confirm(warn)) { return; }
      msg('Cancelling…');
      api('mwm_studio_manage_cancel', {}, function (res) {
        if (res.success) { state.status = state.gt24 ? 'cancelled' : 'cancelled_late'; render(); msg(res.data.message, true); }
        else { msg((res.data && res.data.message) || 'Could not cancel — please try again.'); }
      });
    }

    function pad(n) { return n < 10 ? '0' + n : '' + n; }
    function calRefresh() {
      var box = document.getElementById('mwm-mb-cal');
      if (!box) { return; }
      if (!calY) { var now = new Date(); calY = now.getFullYear(); calM = now.getMonth() + 1; }
      calRender(box, null);
      api('mwm_studio_rental_month', { year: calY, month: calM, duration: state.duration }, function (res) {
        if (!res.success) { calRender(box, {}); msg((res.data && res.data.message) || 'Availability unavailable.'); return; }
        var map = {};
        res.data.days.forEach(function (d) { map[d] = true; });
        calRender(box, map);
      });
    }
    function calRender(box, map) {
      var dows = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
      var months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
      var now = new Date();
      var ymNow = now.getFullYear() * 12 + now.getMonth();
      var ymCal = calY * 12 + (calM - 1);
      var horizon = new Date(now.getTime() + 60 * 86400000);
      var ymHor = horizon.getFullYear() * 12 + horizon.getMonth();
      var startDow = new Date(calY, calM - 1, 1).getDay();
      var dim = new Date(calY, calM, 0).getDate();
      var h = '<div class="mwm-mb-cal-head">';
      h += '<button type="button" class="mwm-mb-cal-nav" id="mwm-mb-prev"' + (ymCal <= ymNow ? ' disabled' : '') + '>&#8249;</button>';
      h += '<div class="mwm-mb-cal-title">' + months[calM - 1] + ' ' + calY + '</div>';
      h += '<button type="button" class="mwm-mb-cal-nav" id="mwm-mb-next"' + (ymCal >= ymHor ? ' disabled' : '') + '>&#8250;</button>';
      h += '</div><div class="mwm-mb-cal-grid">';
      var i;
      for (i = 0; i < 7; i++) { h += '<div class="mwm-mb-cal-dow">' + dows[i] + '</div>'; }
      for (i = 0; i < startDow; i++) { h += '<div></div>'; }
      for (var d = 1; d <= dim; d++) {
        var ds = calY + '-' + pad(calM) + '-' + pad(d);
        var ok = map ? !!map[ds] : false;
        var cls = 'mwm-mb-cal-day' + (ok ? ' mwm-mb-avail' : '') + (ds === pickDate ? ' mwm-mb-on' : '');
        h += '<button type="button" class="' + cls + '" data-d="' + ds + '"' + (ok ? '' : ' disabled') + '>' + d + '</button>';
      }
      h += '</div>';
      box.innerHTML = h;
      var prev = box.querySelector('#mwm-mb-prev');
      var next = box.querySelector('#mwm-mb-next');
      if (prev) { prev.addEventListener('click', function () { calM -= 1; if (calM < 1) { calM = 12; calY -= 1; } calRefresh(); }); }
      if (next) { next.addEventListener('click', function () { calM += 1; if (calM > 12) { calM = 1; calY += 1; } calRefresh(); }); }
      box.querySelectorAll('.mwm-mb-avail').forEach(function (el) {
        el.addEventListener('click', function () {
          pickDate = el.getAttribute('data-d');
          pickSlot = '';
          document.getElementById('mwm-mb-confirm-resched').disabled = true;
          box.querySelectorAll('.mwm-mb-on').forEach(function (o) { o.classList.remove('mwm-mb-on'); });
          el.classList.add('mwm-mb-on');
          loadSlots();
        });
      });
    }
    function loadSlots() {
      var grid = document.getElementById('mwm-mb-slots');
      var lbl = document.getElementById('mwm-mb-slots-label');
      lbl.style.display = 'block';
      grid.innerHTML = '<div class="mwm-mb-msg">Loading times…</div>';
      api('mwm_studio_rental_slots', { date: pickDate, duration: state.duration }, function (res) {
        if (!res.success) { grid.innerHTML = ''; msg((res.data && res.data.message) || 'No times available.'); return; }
        var slots = res.data.slots || [];
        if (!slots.length) { grid.innerHTML = '<div class="mwm-mb-msg">No times left on this day — pick another.</div>'; return; }
        grid.innerHTML = '';
        slots.forEach(function (s) {
          var v = (typeof s === 'string') ? s : (s.start || '');
          var b = document.createElement('button');
          b.type = 'button';
          b.className = 'mwm-mb-slot';
          b.textContent = fmt12(v);
          b.addEventListener('click', function () {
            pickSlot = v;
            grid.querySelectorAll('.mwm-mb-on').forEach(function (o) { o.classList.remove('mwm-mb-on'); });
            b.classList.add('mwm-mb-on');
            document.getElementById('mwm-mb-confirm-resched').disabled = false;
          });
          grid.appendChild(b);
        });
      });
    }
    function doResched() {
      if (!pickDate || !pickSlot) { return; }
      if (!window.confirm('Move your session to ' + pickDate + ' at ' + fmt12(pickSlot) + '?')) { return; }
      msg('Rescheduling…');
      api('mwm_studio_manage_reschedule', { date: pickDate, start_time: pickSlot }, function (res) {
        if (res.success) {
          state.date_label = res.data.date_label;
          state.start = res.data.start;
          state.end = res.data.end;
          render();
          msg(res.data.message, true);
        } else {
          msg((res.data && res.data.message) || 'Could not reschedule — please try again.');
        }
      });
    }

    api('mwm_studio_manage_get', {}, function (res) {
      if (!res.success) { root.innerHTML = '<div class="mwm-mb-msg">' + esc((res.data && res.data.message) || 'Booking not found.') + '</div>'; return; }
      state = res.data;
      render();
    });
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
</script>
MWMJS;
		return $css . $shell . $js;
	}

	/** S19: drop cached day-availability for a date after any booking write. */
	private function clear_rental_day_cache( $date ) {
		for ( $mwm_d = 1; $mwm_d <= 5; $mwm_d++ ) {
			delete_transient( 'mwm_rmday_' . $date . '_' . $mwm_d );
		}
	}

	/** Public slot feed for /book-studio (no login). Same engine as the portal. */
	public function mwm_studio_rental_slots() {
		// S21: PUBLIC read-only availability lookup — intentionally NO nonce.
		// The nonce is baked into the cached /book-studio HTML and expires in ~24h;
		// anonymous visitors on a stale cached page were getting 403 -> the calendar
		// showed "Booking is temporarily unavailable." This endpoint changes no state
		// and returns only public availability, so CSRF protection is unnecessary here.
		// (The booking WRITE, mwm_studio_hold_slot, keeps its nonce.)
		$date     = isset( $_POST['date'] ) ? sanitize_text_field( wp_unslash( $_POST['date'] ) ) : '';
		$duration = isset( $_POST['duration'] ) ? (float) $_POST['duration'] : 1;

		if ( ! $date || ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', $date ) ) {
			wp_send_json_error( array( 'message' => __( 'Invalid date.', 'mwm-studio' ) ) );
		}
		if ( $duration < 1 || $duration > 5 || floor( $duration ) != $duration ) {
			wp_send_json_error( array( 'message' => __( 'Invalid duration.', 'mwm-studio' ) ) );
		}

		$slots = $this->get_available_slots( $date, $duration );
		// S15 fail-closed: NULL = calendar feed down -> never show slots.
		if ( null === $slots ) {
			wp_send_json_error( array(
				'reason'  => 'availability_unavailable',
				'message' => __( 'Booking is temporarily unavailable. Please message us on WhatsApp and we will get you booked.', 'mwm-studio' ),
			) );
		}
		wp_send_json_success( array( 'slots' => $slots ) );
	}

	/** S19: day-level availability for the /book-studio month calendar.
	 *  Derives from get_available_slots (single source of truth, incl. pending
	 *  holds + gcal busy blocks) with a short per-date transient cache. */
	public function mwm_studio_rental_month() {
		// S21: PUBLIC read-only availability lookup — intentionally NO nonce.
		// The nonce is baked into the cached /book-studio HTML and expires in ~24h;
		// anonymous visitors on a stale cached page were getting 403 -> the calendar
		// showed "Booking is temporarily unavailable." This endpoint changes no state
		// and returns only public availability, so CSRF protection is unnecessary here.
		// (The booking WRITE, mwm_studio_hold_slot, keeps its nonce.)
		$year     = isset( $_POST['year'] ) ? (int) $_POST['year'] : 0;
		$month    = isset( $_POST['month'] ) ? (int) $_POST['month'] : 0;
		$duration = isset( $_POST['duration'] ) ? (float) $_POST['duration'] : 1;

		if ( $year < 2020 || $year > 2100 || $month < 1 || $month > 12 ) {
			wp_send_json_error( array( 'message' => __( 'Invalid month.', 'mwm-studio' ) ) );
		}
		if ( $duration < 1 || $duration > 5 || floor( $duration ) != $duration ) {
			wp_send_json_error( array( 'message' => __( 'Invalid duration.', 'mwm-studio' ) ) );
		}

		$today   = date( 'Y-m-d', current_time( 'timestamp' ) );
		$horizon = date( 'Y-m-d', strtotime( $today . ' +60 days' ) );
		$first   = sprintf( '%04d-%02d-01', $year, $month );
		$last    = date( 'Y-m-t', strtotime( $first ) );

		$days   = array();
		$outage = false;
		for ( $d = $first; $d <= $last; $d = date( 'Y-m-d', strtotime( $d . ' +1 day' ) ) ) {
			if ( $d < $today || $d > $horizon ) {
				continue;
			}
			$ck  = 'mwm_rmday_' . $d . '_' . intval( $duration );
			$val = get_transient( $ck );
			if ( false === $val ) {
				$slots = $this->get_available_slots( $d, $duration );
				if ( null === $slots ) {
					$outage = true;
					break;
				}
				$val = count( $slots ) > 0 ? 'y' : 'n';
				set_transient( $ck, $val, 10 * MINUTE_IN_SECONDS );
			}
			if ( 'y' === $val ) {
				$days[] = $d;
			}
		}

		if ( $outage ) {
			wp_send_json_error( array(
				'reason'  => 'availability_unavailable',
				'message' => __( 'Booking is temporarily unavailable. Please message us on WhatsApp and we will get you booked.', 'mwm-studio' ),
			) );
		}
		wp_send_json_success( array( 'days' => $days, 'today' => $today, 'horizon' => $horizon ) );
	}

	/**
	 * Hold a slot, then ask the machine to create a Stripe Checkout Session.
	 * The hold row is written FIRST so the slot is locked while the customer pays.
	 */
	public function mwm_studio_hold_slot() {
		check_ajax_referer( 'mwm_studio_rental', 'nonce' );
		global $wpdb;
		$settings = $this->get_settings();

		$date       = isset( $_POST['date'] ) ? sanitize_text_field( wp_unslash( $_POST['date'] ) ) : '';
		$start_time = isset( $_POST['start_time'] ) ? sanitize_text_field( wp_unslash( $_POST['start_time'] ) ) : '';
		$hours      = isset( $_POST['hours'] ) ? (int) $_POST['hours'] : 0;
		$editing    = ! empty( $_POST['editing'] ) && 'false' !== $_POST['editing'] ? 1 : 0;
		$name       = isset( $_POST['name'] ) ? sanitize_text_field( wp_unslash( $_POST['name'] ) ) : '';
		$email      = isset( $_POST['email'] ) ? sanitize_email( wp_unslash( $_POST['email'] ) ) : '';
		$notes      = isset( $_POST['notes'] ) ? sanitize_textarea_field( wp_unslash( $_POST['notes'] ) ) : '';

		if ( ! $date || ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', $date ) ) {
			wp_send_json_error( array( 'message' => __( 'Invalid date.', 'mwm-studio' ) ) );
		}
		if ( ! $start_time || ! preg_match( '/^\d{2}:\d{2}$/', $start_time ) ) {
			wp_send_json_error( array( 'message' => __( 'Invalid start time.', 'mwm-studio' ) ) );
		}
		if ( $hours < 1 || $hours > 5 ) {
			wp_send_json_error( array( 'message' => __( 'Please choose between 1 and 5 hours.', 'mwm-studio' ) ) );
		}
		if ( ! $name || ! is_email( $email ) ) {
			wp_send_json_error( array( 'message' => __( 'Please enter your name and a valid email.', 'mwm-studio' ) ) );
		}

		// Re-verify the slot is still free (guards the gap between picking and paying).
		$slots = $this->get_available_slots( $date, $hours );
		if ( null === $slots ) {
			wp_send_json_error( array(
				'reason'  => 'availability_unavailable',
				'message' => __( 'Booking is temporarily unavailable. Please message us on WhatsApp.', 'mwm-studio' ),
			) );
		}
		$ok = false;
		foreach ( $slots as $s ) {
			$slot_start = is_array( $s ) ? ( isset( $s['start'] ) ? $s['start'] : '' ) : (string) $s;
			if ( substr( $slot_start, 0, 5 ) === $start_time ) {
				$ok = true;
				break;
			}
		}
		if ( ! $ok ) {
			wp_send_json_error( array( 'message' => __( 'Sorry — that time was just taken. Please pick another slot.', 'mwm-studio' ) ) );
		}

		$end_time    = date( 'H:i:s', strtotime( $date . ' ' . $start_time ) + $hours * HOUR_IN_SECONDS );
		$hold_min    = (int) apply_filters( 'mwm_studio_hold_minutes', 15 );
		$hold_expiry = gmdate( 'Y-m-d H:i:s', time() + $hold_min * MINUTE_IN_SECONDS );

		$inserted = $wpdb->insert(
			$this->bookings_table,
			array(
				'client_id'       => 0,
				'booking_date'    => $date,
				'start_time'      => $start_time . ':00',
				'end_time'        => $end_time,
				'duration_hours'  => $hours,
				'status'          => 'pending_payment',
				'notes'           => $notes,
				'is_rental'       => 1,
				'guest_name'      => $name,
				'guest_email'     => $email,
				'hold_expires_at' => $hold_expiry,
			),
			array( '%d', '%s', '%s', '%s', '%f', '%s', '%s', '%d', '%s', '%s', '%s' )
		);
		if ( ! $inserted ) {
			wp_send_json_error( array( 'message' => __( 'Could not hold that slot. Please try again.', 'mwm-studio' ) ) );
		}
		$booking_id = (int) $wpdb->insert_id;
		$this->clear_rental_day_cache( $date );

		// Ask the machine for a Stripe Checkout URL. It prices the tier itself.
		$machine = get_option( 'mwm_studio_checkout_url', 'https://mwm-sales-agent-production.up.railway.app/studio-checkout' );
		$secret  = get_option( 'mwm_portal_provision_secret', '' );
		$resp    = wp_remote_post( $machine, array(
			'timeout' => 12,
			'headers' => array(
				'Content-Type'        => 'application/json',
				'X-MWM-Portal-Secret' => $secret,
			),
			'body'    => wp_json_encode( array(
				'booking_id' => $booking_id,
				'date'       => $date,
				'start_time' => $start_time,
				'hours'      => $hours,
				'editing'    => (bool) $editing,
				'name'       => $name,
				'email'      => $email,
			) ),
		) );

		if ( is_wp_error( $resp ) || 200 !== wp_remote_retrieve_response_code( $resp ) ) {
			// Release the hold immediately — never strand a slot on our error.
			$wpdb->update( $this->bookings_table, array( 'status' => 'hold_expired' ), array( 'id' => $booking_id ) );
			wp_send_json_error( array( 'message' => __( 'Payment could not be started. Please try again or message us on WhatsApp.', 'mwm-studio' ) ) );
		}

		$body = json_decode( wp_remote_retrieve_body( $resp ), true );
		if ( empty( $body['ok'] ) || empty( $body['url'] ) ) {
			$wpdb->update( $this->bookings_table, array( 'status' => 'hold_expired' ), array( 'id' => $booking_id ) );
			wp_send_json_error( array( 'message' => __( 'Payment could not be started. Please try again.', 'mwm-studio' ) ) );
		}

		$wpdb->update(
			$this->bookings_table,
			array( 'amount_cents' => isset( $body['amount_cents'] ) ? (int) $body['amount_cents'] : null ),
			array( 'id' => $booking_id )
		);

		wp_send_json_success( array(
			'booking_id'   => $booking_id,
			'checkout_url' => esc_url_raw( $body['url'] ),
			'hold_minutes' => $hold_min,
		) );
	}

	/**
	 * Machine-only: Stripe says the rental is PAID -> confirm it and run the
	 * same S12 chain package bookings use (client email + gcal + #matt alert).
	 */
	public function mwm_studio_confirm_rental() {
		global $wpdb;
		$secret = get_option( 'mwm_portal_provision_secret', '' );
		$given  = isset( $_SERVER['HTTP_X_MWM_PORTAL_SECRET'] ) ? sanitize_text_field( wp_unslash( $_SERVER['HTTP_X_MWM_PORTAL_SECRET'] ) ) : '';
		if ( ! $secret || ! hash_equals( $secret, $given ) ) {
			status_header( 401 );
			wp_send_json_error( array( 'message' => 'unauthorized' ) );
		}

		$booking_id  = isset( $_POST['booking_id'] ) ? (int) $_POST['booking_id'] : 0;
		$session_id  = isset( $_POST['session_id'] ) ? sanitize_text_field( wp_unslash( $_POST['session_id'] ) ) : '';
		$amount      = isset( $_POST['amount_cents'] ) ? (int) $_POST['amount_cents'] : 0;

		$booking = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->bookings_table} WHERE id = %d", $booking_id ) );
		if ( ! $booking || ! (int) $booking->is_rental ) {
			wp_send_json_error( array( 'message' => 'booking not found' ) );
		}
		// Idempotent: Stripe retries deliveries.
		if ( 'confirmed' === $booking->status ) {
			wp_send_json_success( array( 'message' => 'already confirmed', 'booking_id' => $booking_id ) );
		}

		$wpdb->update(
			$this->bookings_table,
			array(
				'status'            => 'confirmed',
				'stripe_session_id' => $session_id,
				'amount_cents'      => $amount ? $amount : $booking->amount_cents,
				'hold_expires_at'   => null,
			),
			array( 'id' => $booking_id )
		);
		$this->clear_rental_day_cache( $booking->booking_date );

		$settings = $this->get_settings();
		$start    = substr( $booking->start_time, 0, 5 );
		$end      = substr( $booking->end_time, 0, 5 );
		$paid     = $amount ? number_format( $amount / 100, 2 ) : '';

		$subject  = sprintf( 'Booking confirmed — %s at %s | %s', mwm_sb_d12( $booking->booking_date ), mwm_sb_t12( $start ), $settings['studio_name'] );
		$mwm_rows = array(
			'Date'     => date_i18n( 'l, F j, Y', strtotime( $booking->booking_date ) ),
			'Time'     => mwm_sb_t12( $start ) . ' – ' . mwm_sb_t12( $end ),
			'Duration' => $booking->duration_hours . ' hour(s)',
		);
		if ( $paid ) {
			$mwm_rows['Amount Paid'] = '$' . $paid . ' USD';
		}
		$mwm_rows['Location'] = $settings['studio_name'] . ', ' . $settings['studio_address'];
		$mwm_html = $this->get_branded_email_html( array(
			'eyebrow'    => 'Payment Received',
			'title'      => 'Your Studio Session Is Confirmed',
			'preheader'  => sprintf( 'Your studio session on %s at %s is confirmed and paid.', date_i18n( 'F j, Y', strtotime( $booking->booking_date ) ), $start ),
			'name'       => $booking->guest_name,
			'intro'      => 'Thank you — your payment went through and your studio session is confirmed. Here are your details:',
			'rows'       => $mwm_rows,
			'body_after' => 'Need to change plans? Up to <strong>24 hours</strong> before your session you can reschedule free of charge, or cancel for a refund minus payment-processing fees — use the Manage Booking button below. Within 24 hours of the session, the booking is non-refundable and rebooking requires a new payment. A calendar invite (.ics) is attached.',
			'cta_label'  => 'Manage Your Booking',
			'cta_url'    => $this->manage_url( $booking ),
			'outro'      => 'See you at the studio!',
		) );
		$this->notify_client_html_ics( $booking->guest_email, $subject, $mwm_html, $booking );
		$this->notify_admin(
			sprintf( 'PAID studio rental — %s (%s)', $booking->guest_name, $booking->guest_email ),
			sprintf( "%s %s–%s (%sh) — $%s\nBooking #%d", $booking->booking_date, $start, $end, $booking->duration_hours, $paid, $booking_id )
		);

		$this->push_booking_event( 'booking_created', array(
			'booking_id'   => $booking_id,
			'client_name'  => $booking->guest_name . ' (rental)',
			'client_email' => $booking->guest_email,
			'date'         => $booking->booking_date,
			'start_time'   => $start,
			'end_time'     => $end,
			'duration'     => $booking->duration_hours,
			'notes'        => $booking->notes,
		) );

		wp_send_json_success( array( 'message' => 'confirmed', 'booking_id' => $booking_id ) );
	}

	public function mwm_studio_cancel_booking() {
		$client   = $this->authenticate_request();
		$settings = $this->get_settings();
		global $wpdb;

		$booking_id = isset( $_POST['booking_id'] ) ? (int) $_POST['booking_id'] : 0;
		if ( ! $booking_id ) {
			wp_send_json_error( array( 'message' => __( 'Invalid booking.', 'mwm-studio' ) ) );
		}

		$booking = $wpdb->get_row(
			$wpdb->prepare(
				"SELECT * FROM {$this->bookings_table} WHERE id = %d AND client_id = %d",
				$booking_id,
				$client->id
			)
		);

		if ( ! $booking ) {
			wp_send_json_error( array( 'message' => __( 'Booking not found.', 'mwm-studio' ) ) );
		}
		if ( 'confirmed' !== $booking->status ) {
			wp_send_json_error( array( 'message' => __( 'This booking cannot be cancelled.', 'mwm-studio' ) ) );
		}

		$start_ts    = strtotime( $booking->booking_date . ' ' . $booking->start_time );
		$hours_until = ( $start_ts - current_time( 'timestamp' ) ) / HOUR_IN_SECONDS;

		if ( $hours_until < (int) $settings['cancellation_hours'] ) {
			wp_send_json_error(
				array(
					'message' => sprintf(
						/* translators: %d: cancellation cutoff hours */
						__( 'Bookings must be cancelled at least %d hours in advance.', 'mwm-studio' ),
						(int) $settings['cancellation_hours']
					),
				)
			);
		}

	// S7.6 (Michael, Jul 6 2026): 24h cancellation policy — sessions cancelled
	// with <24h notice keep their hours charged ('cancelled_late' counts in the
	// hours-used sums but frees the calendar slot).
	$mwm_sess_ts     = strtotime( trim( $booking->booking_date . ' ' . ( isset( $booking->start_time ) && $booking->start_time ? $booking->start_time : '00:00:00' ) ) );
	$mwm_late_cancel = ( $mwm_sess_ts && ( $mwm_sess_ts - current_time( 'timestamp' ) ) < DAY_IN_SECONDS );
		$wpdb->update(
			$this->bookings_table,
			array(
				'status' => ( $mwm_late_cancel ? 'cancelled_late' : 'cancelled' ),
				'cancelled_at' => current_time( 'mysql' ),
			),
			array( 'id' => $booking_id ),
			array( '%s', '%s' ),
			array( '%d' )
		);

		$this->clear_rental_day_cache( $booking->booking_date );

		$subject = sprintf( '[%s] Booking Cancelled: %s', $settings['studio_name'], $client->name );
		$message = sprintf(
			"A studio booking has been cancelled.\n\nClient: %s (%s)\nDate: %s\nTime: %s - %s\n",
			$client->name,
			$client->email,
			date_i18n( 'l, F j, Y', strtotime( $booking->booking_date ) ),
			mwm_sb_t12( $booking->start_time ),
			mwm_sb_t12( $booking->end_time )
		);
		$this->notify_admin( $subject, $message );

		// S12: client cancellation email + machine push
		$mwm_client_subject = sprintf( 'Booking cancelled — %s at %s | %s', $booking->booking_date, substr( $booking->start_time, 0, 5 ), $settings['studio_name'] );
		if ( $mwm_late_cancel ) {
			$mwm_policy_line = sprintf( 'Because this cancellation was within <strong>%d hours</strong> of the session, the booked hours were deducted from your package per your agreement.', intval( $settings['cancellation_hours'] ) );
		} else {
			$mwm_policy_line = 'Your hours were returned to your package — nothing was deducted.';
		}
		$mwm_client_html = $this->get_branded_email_html( array(
			'eyebrow'    => 'Booking Cancelled',
			'title'      => 'Your Session Was Cancelled',
			'preheader'  => sprintf( 'Your studio session on %s was cancelled.', date_i18n( 'F j, Y', strtotime( $booking->booking_date ) ) ),
			'name'       => $client->name,
			'rows'       => array(
				'Date' => date_i18n( 'l, F j, Y', strtotime( $booking->booking_date ) ),
				'Time' => substr( $booking->start_time, 0, 5 ) . ' – ' . substr( $booking->end_time, 0, 5 ),
			),
			'intro'      => 'Your studio session below has been cancelled.',
			'body_after' => $mwm_policy_line . ' You can book a new session any time from your client portal.',
			'cta_label'  => 'Book a New Session',
			'cta_url'    => 'https://mwmcreations.com/studio-portal/',
			'outro'      => 'Hope to see you back at the studio soon,',
		) );
		$this->notify_client_html( $client->email, $mwm_client_subject, $mwm_client_html );
		$this->push_booking_event( $mwm_late_cancel ? 'booking_cancelled_late' : 'booking_cancelled', array(
			'booking_id'   => $booking_id,
			'client_name'  => $client->name,
			'client_email' => $client->email,
			'date'         => $booking->booking_date,
			'start_time'   => substr( $booking->start_time, 0, 5 ),
			'end_time'     => substr( $booking->end_time, 0, 5 ),
		) );

		wp_send_json_success( array( 'message' => ( $mwm_late_cancel ? __( 'Session cancelled. Because this was within 24 hours of your session, the booked hours remain charged per our cancellation policy.', 'mwm-studio' ) : __( 'Booking cancelled.', 'mwm-studio' ) ) ) );
	}

	/* =========================================================================
	 * AJAX: RECORD CALENDLY BOOKING
	 * ========================================================================= */

	public function mwm_studio_record_calendly_booking() {
		$client = $this->authenticate_request();
		global $wpdb;

		$event_uri   = isset( $_POST['event_uri'] ) ? sanitize_text_field( wp_unslash( $_POST['event_uri'] ) ) : '';
		$invitee_uri = isset( $_POST['invitee_uri'] ) ? sanitize_text_field( wp_unslash( $_POST['invitee_uri'] ) ) : '';

		// Record a 1-hour booking for the current date as a placeholder.
		// The admin can adjust the actual duration in the Bookings admin page.
		// In the future, this could query the Calendly API for exact event details.
		$booking_date = current_time( 'Y-m-d' );
		$start_time   = current_time( 'H:i:s' );
		$end_time     = date( 'H:i:s', strtotime( $start_time . ' +1 hour' ) );
		$duration     = 1.00;

		$wpdb->insert(
			$this->bookings_table,
			array(
				'client_id'      => $client->id,
				'booking_date'   => $booking_date,
				'start_time'     => $start_time,
				'end_time'       => $end_time,
				'duration_hours' => $duration,
				'status'         => 'confirmed',
				'notes'          => $event_uri ? 'Calendly: ' . $event_uri : 'Booked via Calendly',
			),
			array( '%d', '%s', '%s', '%s', '%f', '%s', '%s' )
		);

		if ( $wpdb->insert_id ) {
			wp_send_json_success( array(
				'booking_id' => $wpdb->insert_id,
				'message'    => 'Booking recorded successfully.',
			) );
		} else {
			wp_send_json_error( array( 'message' => 'Failed to record booking.' ) );
		}
	}

	/* =========================================================================
	 * ADMIN MENU
	 * ========================================================================= */

	public function admin_menu() {
		add_menu_page(
			__( 'Studio Bookings', 'mwm-studio' ),
			__( 'Studio Bookings', 'mwm-studio' ),
			'manage_options',
			'mwm-studio-dashboard',
			array( $this, 'render_dashboard_page' ),
			'dashicons-calendar-alt',
			26
		);
		add_submenu_page( 'mwm-studio-dashboard', __( 'Dashboard', 'mwm-studio' ), __( 'Dashboard', 'mwm-studio' ), 'manage_options', 'mwm-studio-dashboard', array( $this, 'render_dashboard_page' ) );
		add_submenu_page( 'mwm-studio-dashboard', __( 'Clients', 'mwm-studio' ), __( 'Clients', 'mwm-studio' ), 'manage_options', 'mwm-studio-clients', array( $this, 'render_clients_page' ) );
		add_submenu_page( 'mwm-studio-dashboard', __( 'Bookings', 'mwm-studio' ), __( 'Bookings', 'mwm-studio' ), 'manage_options', 'mwm-studio-bookings', array( $this, 'render_bookings_page' ) );
		add_submenu_page( 'mwm-studio-dashboard', __( 'Settings', 'mwm-studio' ), __( 'Settings', 'mwm-studio' ), 'manage_options', 'mwm-studio-settings', array( $this, 'render_settings_page' ) );
		// S26 — admin booking control.
		add_submenu_page( 'mwm-studio-dashboard', __( 'Reconciliation', 'mwm-studio' ), __( 'Reconciliation', 'mwm-studio' ), 'manage_options', 'mwm-studio-reconcile', array( $this, 'render_reconcile_page' ) );
		add_submenu_page( 'mwm-studio-dashboard', __( 'Audit Trail', 'mwm-studio' ), __( 'Audit Trail', 'mwm-studio' ), 'manage_options', 'mwm-studio-audit', array( $this, 'render_audit_page' ) );
		// Kept as a real submenu row on purpose: remove_submenu_page() would strip the
		// entry user_can_access_admin_page() walks to resolve the parent, and every
		// ?page=mwm-studio-booking-edit hit would 'Sorry, you are not allowed'.
		add_submenu_page( 'mwm-studio-dashboard', __( 'Add / Edit Booking', 'mwm-studio' ), __( 'Add / Edit Booking', 'mwm-studio' ), 'manage_options', 'mwm-studio-booking-edit', array( $this, 'render_booking_edit_page' ) );
	}

	/**
	 * Handle admin POST actions (create/update/delete client, cancel/complete booking, save settings).
	 * Runs on admin_init so redirects work cleanly.
	 */
	public function handle_admin_actions() {
		if ( ! is_admin() || ! current_user_can( 'manage_options' ) ) {
			return;
		}
		if ( empty( $_POST['mwm_studio_action'] ) ) {
			// Handle simple GET actions (delete / cancel / complete via link).
			$this->handle_admin_get_actions();
			return;
		}

		$action = sanitize_text_field( wp_unslash( $_POST['mwm_studio_action'] ) );

		if ( 'save_client' === $action ) {
			check_admin_referer( 'mwm_studio_save_client' );
			$this->admin_save_client();
		} elseif ( 'save_settings' === $action ) {
			check_admin_referer( 'mwm_studio_save_settings' );
			$this->admin_save_settings();
		} elseif ( 'save_booking' === $action ) {
			// S26: create or edit a booking through the single write path.
			check_admin_referer( 'mwm_studio_save_booking' );
			$this->admin_save_booking();
		} elseif ( 'adjust_hours' === $action ) {
			// S26: add hours to a package / change the contract total.
			check_admin_referer( 'mwm_studio_adjust_hours' );
			$this->admin_adjust_hours();
		}
	}

	private function handle_admin_get_actions() {
		if ( empty( $_GET['mwm_action'] ) ) {
			return;
		}
		$mwm_action = sanitize_text_field( wp_unslash( $_GET['mwm_action'] ) );
		global $wpdb;

		if ( 'delete_client' === $mwm_action && isset( $_GET['id'] ) ) {
			check_admin_referer( 'mwm_studio_delete_client_' . (int) $_GET['id'] );
			$id = (int) $_GET['id'];
			$wpdb->delete( $this->clients_table, array( 'id' => $id ), array( '%d' ) );
			wp_safe_redirect( admin_url( 'admin.php?page=mwm-studio-clients&deleted=1' ) );
			exit;
		}

		if ( 'cancel_booking' === $mwm_action && isset( $_GET['id'] ) ) {
			check_admin_referer( 'mwm_studio_cancel_booking_' . (int) $_GET['id'] );
			$id = (int) $_GET['id'];
			// S26: was a bare $wpdb->update — it wrote the row and pushed nothing, so
			// cancelling here left the Google Calendar event in place, blocking the
			// studio forever. Now it goes through the single write path.
			$res = $this->admin_write_booking( $id, array( 'status' => 'cancelled' ), array( 'action' => 'booking.cancel', 'reason' => 'Cancelled from the Bookings list' ) );
			if ( ! $res['ok'] ) {
				set_transient( 'mwm_studio_admin_error', $res['message'], 60 );
			}
			wp_safe_redirect( admin_url( 'admin.php?page=mwm-studio-bookings&cancelled=1' ) );
			exit;
		}

		if ( 'complete_booking' === $mwm_action && isset( $_GET['id'] ) ) {
			check_admin_referer( 'mwm_studio_complete_booking_' . (int) $_GET['id'] );
			$id = (int) $_GET['id'];
			// S26: same write path. Completing does not move the session, so the
			// calendar event is deliberately left alone.
			$res = $this->admin_write_booking( $id, array( 'status' => 'completed' ), array( 'action' => 'booking.complete', 'reason' => 'Marked completed from the Bookings list' ) );
			if ( ! $res['ok'] ) {
				set_transient( 'mwm_studio_admin_error', $res['message'], 60 );
			}
			wp_safe_redirect( admin_url( 'admin.php?page=mwm-studio-bookings&completed=1' ) );
			exit;
		}

		if ( 'rotate_qb' === $mwm_action ) {
			// S27: kills the old quick-book link AND the PIN in one move — the
			// recovery path for a lost phone or a forgotten PIN.
			check_admin_referer( 'mwm_studio_rotate_qb' );
			delete_option( 'mwm_studio_qb_token' );
			delete_option( 'mwm_studio_qb_pin' );
			$this->qb_token(); // mint a fresh one straight away
			$this->audit_log( 'quickbook.rotate', 0, 0, null, null, 'Link rotated and PIN cleared from Settings' );
			wp_safe_redirect( admin_url( 'admin.php?page=mwm-studio-settings&rotated=1' ) );
			exit;
		}

		if ( 'regenerate_code' === $mwm_action && isset( $_GET['id'] ) ) {
			check_admin_referer( 'mwm_studio_regen_' . (int) $_GET['id'] );
			$id   = (int) $_GET['id'];
			$code = $this->generate_access_code();
			$wpdb->update(
				$this->clients_table,
				array( 'access_code' => wp_hash_password( $code ) ),
				array( 'id' => $id ),
				array( '%s' ),
				array( '%d' )
			);
			set_transient( 'mwm_studio_new_code_' . $id, $code, MINUTE_IN_SECONDS );
			wp_safe_redirect( admin_url( 'admin.php?page=mwm-studio-clients&regenerated=' . $id ) );
			exit;
		}
	}

	private function admin_save_client() {
		global $wpdb;

		$id                  = isset( $_POST['client_id'] ) ? (int) $_POST['client_id'] : 0;
		$name                = isset( $_POST['name'] ) ? sanitize_text_field( wp_unslash( $_POST['name'] ) ) : '';
		$email               = isset( $_POST['email'] ) ? sanitize_email( wp_unslash( $_POST['email'] ) ) : '';
		$phone               = isset( $_POST['phone'] ) ? sanitize_text_field( wp_unslash( $_POST['phone'] ) ) : '';
		$company             = isset( $_POST['company'] ) ? sanitize_text_field( wp_unslash( $_POST['company'] ) ) : '';
		$package_name        = isset( $_POST['package_name'] ) ? sanitize_text_field( wp_unslash( $_POST['package_name'] ) ) : '';
		$monthly_hours       = isset( $_POST['monthly_hours'] ) ? (float) $_POST['monthly_hours'] : 4.0;
		$contract_hours      = isset( $_POST['contract_hours'] ) ? (float) $_POST['contract_hours'] : 12.0;
		$contract_start_date = isset( $_POST['contract_start_date'] ) && $_POST['contract_start_date'] ? sanitize_text_field( wp_unslash( $_POST['contract_start_date'] ) ) : null;
		$contract_end_date   = isset( $_POST['contract_end_date'] ) && $_POST['contract_end_date'] ? sanitize_text_field( wp_unslash( $_POST['contract_end_date'] ) ) : null;
		$active              = isset( $_POST['active'] ) ? 1 : 0;
		$notes               = isset( $_POST['notes'] ) ? sanitize_textarea_field( wp_unslash( $_POST['notes'] ) ) : '';
		$access_code         = isset( $_POST['access_code'] ) ? strtoupper( sanitize_text_field( wp_unslash( $_POST['access_code'] ) ) ) : '';

		// Auto-calculate contract end date if start is set but end is empty (3 months from start).
		if ( $contract_start_date && ! $contract_end_date ) {
			$contract_end_date = date( 'Y-m-d', strtotime( $contract_start_date . ' +3 months' ) );
		}

		if ( empty( $name ) || empty( $email ) || ! is_email( $email ) ) {
			set_transient( 'mwm_studio_admin_error', __( 'Name and a valid email are required.', 'mwm-studio' ), 30 );
			wp_safe_redirect( wp_get_referer() );
			exit;
		}

		$data = array(
			'name'                => $name,
			'email'               => $email,
			'phone'               => $phone,
			'company'             => $company,
			'package_name'        => $package_name,
			'monthly_hours'       => $monthly_hours,
			'contract_hours'      => $contract_hours,
			'contract_start_date' => $contract_start_date,
			'contract_end_date'   => $contract_end_date,
			'active'              => $active,
			'notes'               => $notes,
			'updated_at'          => current_time( 'mysql' ),
		);
		$formats = array( '%s', '%s', '%s', '%s', '%s', '%f', '%f', '%s', '%s', '%d', '%s', '%s' );

		if ( $id ) {
			if ( ! empty( $access_code ) ) {
				$data['access_code'] = wp_hash_password( $access_code );
				$formats[]           = '%s';
			}
			$wpdb->update( $this->clients_table, $data, array( 'id' => $id ), $formats, array( '%d' ) );
			$msg = 'updated';
		} else {
			if ( empty( $access_code ) ) {
				$access_code = $this->generate_access_code();
			}
			$data['access_code'] = wp_hash_password( $access_code );
			$data['created_at']  = current_time( 'mysql' );
			$formats[]           = '%s';
			$formats[]           = '%s';
			$wpdb->insert( $this->clients_table, $data, $formats );
			$id = $wpdb->insert_id;
			set_transient( 'mwm_studio_new_code_' . $id, $access_code, 5 * MINUTE_IN_SECONDS );
			$msg = 'created';
		}

		wp_safe_redirect( admin_url( 'admin.php?page=mwm-studio-clients&' . $msg . '=' . $id ) );
		exit;
	}

	private function admin_save_settings() {
		$settings = $this->get_settings();

		// S27: stored on its own so it never rides in the settings blob.
		if ( isset( $_POST['drift_slack'] ) ) {
			update_option( 'mwm_studio_drift_slack', esc_url_raw( wp_unslash( $_POST['drift_slack'] ) ), false );
		}

		$settings['studio_name']        = isset( $_POST['studio_name'] ) ? sanitize_text_field( wp_unslash( $_POST['studio_name'] ) ) : $settings['studio_name'];
		$settings['studio_address']     = isset( $_POST['studio_address'] ) ? sanitize_text_field( wp_unslash( $_POST['studio_address'] ) ) : $settings['studio_address'];
		$settings['min_booking_hours']  = isset( $_POST['min_booking_hours'] ) ? (float) $_POST['min_booking_hours'] : $settings['min_booking_hours'];
		$settings['max_advance_days']   = isset( $_POST['max_advance_days'] ) ? (int) $_POST['max_advance_days'] : $settings['max_advance_days'];
		$settings['cancellation_hours'] = isset( $_POST['cancellation_hours'] ) ? (int) $_POST['cancellation_hours'] : $settings['cancellation_hours'];
		$settings['buffer_minutes']     = isset( $_POST['buffer_minutes'] ) ? (int) $_POST['buffer_minutes'] : $settings['buffer_minutes'];

		// Stripe settings
		$settings['stripe_webhook_secret']     = isset( $_POST['stripe_webhook_secret'] ) ? sanitize_text_field( wp_unslash( $_POST['stripe_webhook_secret'] ) ) : $settings['stripe_webhook_secret'];
		$settings['stripe_package_product_id'] = isset( $_POST['stripe_package_product_id'] ) ? sanitize_text_field( wp_unslash( $_POST['stripe_package_product_id'] ) ) : $settings['stripe_package_product_id'];
		$settings['stripe_contract_hours']     = isset( $_POST['stripe_contract_hours'] ) ? (float) $_POST['stripe_contract_hours'] : $settings['stripe_contract_hours'];
		$settings['stripe_contract_months']    = isset( $_POST['stripe_contract_months'] ) ? (int) $_POST['stripe_contract_months'] : $settings['stripe_contract_months'];

		$days = array( 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday' );
		foreach ( $days as $day ) {
			$settings['hours'][ $day ] = array(
				'open'   => isset( $_POST[ 'open_' . $day ] ) ? sanitize_text_field( wp_unslash( $_POST[ 'open_' . $day ] ) ) : '09:00',
				'close'  => isset( $_POST[ 'close_' . $day ] ) ? sanitize_text_field( wp_unslash( $_POST[ 'close_' . $day ] ) ) : '18:00',
				'closed' => isset( $_POST[ 'closed_' . $day ] ) ? 1 : 0,
			);
		}

		update_option( $this->settings_option, $settings );
		wp_safe_redirect( admin_url( 'admin.php?page=mwm-studio-settings&saved=1' ) );
		exit;
	}

	/* =========================================================================
	 * ADMIN PAGE: DASHBOARD
	 * ========================================================================= */


	/* =========================================================================
	 * S26 — ADMIN BOOKING CONTROL (Aug 13 2026, Michael)
	 *
	 * "we need to be able to add hours, have more control... they wanna go over
	 *  and use more time, and we need to be able to have that flexibility to go
	 *  into their portal and adjust that... I don't want you to have to manually
	 *  code times like you had to do this time."
	 *
	 * 🔴 THE DESIGN RULE: ONE WRITE PATH. Every admin mutation of a booking goes
	 * through admin_write_booking(). In a single operation it writes the row,
	 * pushes the calendar to match, and records an audit entry with the before
	 * value. Nothing else in this plugin may UPDATE the bookings table from an
	 * admin screen.
	 *
	 * The hours ledger is DERIVED, not stored — hours_used_in_contract() SUMs
	 * duration_hours over the contract window. Writing the row IS moving the
	 * ledger; there is no second number that can drift from it.
	 *
	 * Why the calendar is removed-and-recreated rather than updated: the machine
	 * webhook (/webhook/studio-booking) accepts only booking_created /
	 * booking_cancelled / booking_cancelled_late and 400s on anything else.
	 * There is no booking_updated. The client-facing reschedule already solves
	 * this with a bumped idempotency id (61, 61-r1, 61-r2...) via event_bid();
	 * this reuses that exact mechanism, so S26 ships WordPress-side with no
	 * machine deploy.
	 *
	 * Background — what this replaced: booking #61 (Jonathan Pineda, Aug 13
	 * 2026) read 15:00 in the row and 14:15 on the calendar because the calendar
	 * event had been hand-edited and nothing reconciled the two. The reminder
	 * email reads the ROW, so the client was told the wrong time. Admin Cancel
	 * and Mark Completed also wrote the row and pushed nothing, leaving orphan
	 * events that block the studio forever. Both are closed here.
	 * ========================================================================= */

	/** S26: statuses whose booking occupies the studio and must have a calendar event. */
	private function status_holds_calendar( $status ) {
		return in_array( (string) $status, array( 'confirmed', 'completed' ), true );
	}

	/**
	 * S26: statuses that DRAW HOURS from the package. Deliberately not the same
	 * set as status_holds_calendar(): a late cancellation frees the studio but
	 * still charges the hours (S7.6, Michael, Jul 6 2026). Mixing the two sets up
	 * is how a ledger double-counts.
	 */
	private function status_counts_hours( $status ) {
		return in_array( (string) $status, array( 'confirmed', 'completed', 'cancelled_late' ), true );
	}

	/** S26: statuses an admin may set. */
	private function admin_allowed_statuses() {
		return array( 'confirmed', 'completed', 'cancelled', 'cancelled_late' );
	}

	/** S26: audit trail — who changed what, when, and the value it held before. */
	private function audit_log( $action, $booking_id, $client_id, $before, $after, $reason = '', $actor = '' ) {
		global $wpdb;
		$user = wp_get_current_user();
		// S27: the quick-book page has no WordPress session, so it names itself.
		$actor_name = $actor ? $actor : ( $user && $user->ID ? $user->user_login : 'system' );
		$wpdb->insert(
			$this->audit_table,
			array(
				'booking_id'  => $booking_id ? (int) $booking_id : null,
				'client_id'   => $client_id ? (int) $client_id : null,
				'actor_id'    => $user ? (int) $user->ID : null,
				'actor_name'  => $actor_name,
				'action'      => substr( (string) $action, 0, 40 ),
				'before_json' => null === $before ? null : wp_json_encode( $before ),
				'after_json'  => null === $after ? null : wp_json_encode( $after ),
				'reason'      => substr( (string) $reason, 0, 255 ),
				'created_at'  => current_time( 'mysql' ),
			),
			array( '%d', '%d', '%d', '%s', '%s', '%s', '%s', '%s', '%s' )
		);
	}

	/** S26: display label for a booking's client (package client or rental guest). */
	private function booking_client_label( $client_id, $booking = null ) {
		if ( $client_id ) {
			$c = $this->get_client( $client_id );
			if ( $c ) {
				return $c->name;
			}
		}
		if ( $booking && ! empty( $booking->guest_name ) ) {
			return $booking->guest_name . ' (rental)';
		}
		return 'Studio booking';
	}

	/** S26: client email for a booking (package client or rental guest). */
	private function booking_client_email( $client_id, $booking = null ) {
		if ( $client_id ) {
			$c = $this->get_client( $client_id );
			if ( $c ) {
				return $c->email;
			}
		}
		return $booking && ! empty( $booking->guest_email ) ? $booking->guest_email : '';
	}

	/**
	 * S26 — THE SINGLE WRITE PATH.
	 *
	 * @param int   $booking_id 0 to create, otherwise the booking to change.
	 * @param array $fields     client_id, booking_date, start_time (H:i), duration_hours, status, notes.
	 *                          Omitted keys keep their current value on an edit.
	 * @param array $opts       reason, notify_client (bool), allow_conflict (bool), action (audit label).
	 * @return array{ok:bool,booking_id:int,message:string,warnings:string[]}
	 */
	private function admin_write_booking( $booking_id, $fields, $opts = array() ) {
		global $wpdb;

		$opts = wp_parse_args(
			$opts,
			array(
				'reason'         => '',
				'notify_client'  => false,
				'allow_conflict' => false,
				'action'         => '',
				'actor'          => '',
				/*
				 * S28 — push_calendar (default TRUE) is the ONE change S26's write
				 * path needed to accept a change that came FROM the calendar.
				 *
				 * When the drag happened on Google Calendar, the calendar is
				 * ALREADY in the target state. Pushing would delete the event
				 * Michael just dragged and replace it with an identical one under
				 * a new id, e-mailing the client a cancellation and a fresh invite
				 * for no reason. This is not skipping reconciliation; it is
				 * recognising the reconciliation has already happened.
				 *
				 * Validation, the overlap check, the hours maths and the audit
				 * entry all still run. Only the two push_booking_event() calls and
				 * the reschedule_count bump are skipped.
				 *
				 * WARNING: reachable ONLY from handle_calendar_sync() and
				 * cal_answer_handler(). It must NEVER be exposed in a form, a query
				 * string, or the quick-book page — the next person will be tempted.
				 */
				'push_calendar'     => true,
				/*
				 * S28 — calendar_recreate: "No, put it back" after a deletion. The
				 * event is already gone, so the usual remove-the-old-one push would
				 * ask the machine to delete something that does not exist and post a
				 * STUDIO CANCELLATION alert for a booking nobody cancelled. This
				 * skips the removal and forces the creation, with a fresh
				 * reschedule_count so the new event gets its own idempotency id.
				 * Same access rule as push_calendar: internal callers only.
				 */
				'calendar_recreate' => false,
			)
		);
		$warnings = array();

		$booking_id = (int) $booking_id;
		$before     = $booking_id
			? $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->bookings_table} WHERE id = %d", $booking_id ) )
			: null;

		if ( $booking_id && ! $before ) {
			return array( 'ok' => false, 'booking_id' => 0, 'message' => __( 'That booking no longer exists.', 'mwm-studio' ), 'warnings' => array() );
		}

		/* ---- resolve target state (omitted keys keep their current value) ---- */
		$client_id = array_key_exists( 'client_id', $fields ) ? (int) $fields['client_id'] : ( $before ? (int) $before->client_id : 0 );
		$date      = array_key_exists( 'booking_date', $fields ) ? trim( (string) $fields['booking_date'] ) : ( $before ? $before->booking_date : '' );
		$start     = array_key_exists( 'start_time', $fields ) ? substr( trim( (string) $fields['start_time'] ), 0, 5 ) : ( $before ? substr( $before->start_time, 0, 5 ) : '' );
		$duration  = array_key_exists( 'duration_hours', $fields ) ? (float) $fields['duration_hours'] : ( $before ? (float) $before->duration_hours : 0.0 );
		$status    = array_key_exists( 'status', $fields ) ? (string) $fields['status'] : ( $before ? (string) $before->status : 'confirmed' );
		$notes     = array_key_exists( 'notes', $fields ) ? (string) $fields['notes'] : ( $before ? (string) $before->notes : '' );

		/* ---- validate ---- */
		if ( ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', $date ) || ! strtotime( $date ) ) {
			return array( 'ok' => false, 'booking_id' => $booking_id, 'message' => __( 'Enter a valid date (YYYY-MM-DD).', 'mwm-studio' ), 'warnings' => array() );
		}
		if ( ! preg_match( '/^([01]\d|2[0-3]):([0-5]\d)$/', $start ) ) {
			return array( 'ok' => false, 'booking_id' => $booking_id, 'message' => __( 'Enter a valid start time (HH:MM, 24-hour).', 'mwm-studio' ), 'warnings' => array() );
		}
		// Free-form duration: any quarter hour from 0.25 to 12. 1.5 is exactly as easy as 1.0.
		if ( $duration < 0.25 || $duration > 12 ) {
			return array( 'ok' => false, 'booking_id' => $booking_id, 'message' => __( 'Duration must be between 0.25 and 12 hours.', 'mwm-studio' ), 'warnings' => array() );
		}
		if ( abs( ( $duration * 4 ) - round( $duration * 4 ) ) > 0.0001 ) {
			return array( 'ok' => false, 'booking_id' => $booking_id, 'message' => __( 'Duration must be a multiple of 0.25 hours (15 minutes).', 'mwm-studio' ), 'warnings' => array() );
		}
		$duration = round( $duration * 4 ) / 4;
		if ( ! in_array( $status, $this->admin_allowed_statuses(), true ) ) {
			return array( 'ok' => false, 'booking_id' => $booking_id, 'message' => __( 'Unknown status.', 'mwm-studio' ), 'warnings' => array() );
		}
		$is_rental = $before ? (int) $before->is_rental : 0;
		if ( ! $client_id && ! $is_rental ) {
			return array( 'ok' => false, 'booking_id' => $booking_id, 'message' => __( 'Pick a client.', 'mwm-studio' ), 'warnings' => array() );
		}
		$client = $client_id ? $this->get_client( $client_id ) : null;
		if ( $client_id && ! $client ) {
			return array( 'ok' => false, 'booking_id' => $booking_id, 'message' => __( 'That client no longer exists.', 'mwm-studio' ), 'warnings' => array() );
		}

		$start_sql = $start . ':00';
		$end_ts    = strtotime( $date . ' ' . $start_sql ) + (int) round( $duration * HOUR_IN_SECONDS );
		$end_sql   = date( 'H:i:s', $end_ts );
		if ( date( 'Y-m-d', $end_ts ) !== $date ) {
			return array( 'ok' => false, 'booking_id' => $booking_id, 'message' => __( 'That session would run past midnight. Shorten it or move the start time.', 'mwm-studio' ), 'warnings' => array() );
		}

		/* ---- studio double-booking guard (overridable, never silent) ---- */
		if ( $this->status_holds_calendar( $status ) ) {
			$clash = $wpdb->get_row(
				$wpdb->prepare(
					"SELECT id, booking_date, start_time, end_time FROM {$this->bookings_table}
					WHERE booking_date = %s AND id <> %d
					AND status IN ('confirmed','completed')
					AND start_time < %s AND end_time > %s
					LIMIT 1",
					$date,
					$booking_id,
					$end_sql,
					$start_sql
				)
			);
			if ( $clash ) {
				if ( ! $opts['allow_conflict'] ) {
					return array(
						'ok'         => false,
						'booking_id' => $booking_id,
						'message'    => sprintf(
							/* translators: 1: booking id, 2: start, 3: end */
							__( 'That overlaps booking #%1$d (%2$s–%3$s). Tick "allow overlap" if you really mean to double-book the studio.', 'mwm-studio' ),
							(int) $clash->id,
							substr( $clash->start_time, 0, 5 ),
							substr( $clash->end_time, 0, 5 )
						),
						'warnings'   => array(),
					);
				}
				$warnings[] = sprintf( __( 'Overlaps booking #%d — saved anyway because you allowed it.', 'mwm-studio' ), (int) $clash->id );
			}
		}

		/* ---- hours ledger (derived) — allow past total, flag it loudly ---- */
		$over_by = 0.0;
		if ( $client ) {
			// hours_used_in_contract() already includes the CURRENT state of this row,
			// so subtract what it contributes today before adding what it will contribute.
			$used_now  = $this->hours_used_in_contract( $client->id, $client->contract_start_date, $client->contract_end_date );
			$was       = ( $before && $this->status_counts_hours( $before->status ) && $this->booking_in_contract( $before, $client ) ) ? (float) $before->duration_hours : 0.0;
			$will      = ( $this->status_counts_hours( $status ) && $this->booking_in_contract( (object) array( 'booking_date' => $date ), $client ) ) ? $duration : 0.0;
			$projected = $used_now - $was + $will;
			if ( $projected > (float) $client->contract_hours + 0.001 ) {
				$over_by    = $projected - (float) $client->contract_hours;
				$warnings[] = sprintf(
					/* translators: 1: client name, 2: hours over, 3: used, 4: total */
					__( '%1$s is now %2$s hours OVER contract (%3$s / %4$s). Saved — add hours to the package or bill the overage.', 'mwm-studio' ),
					$client->name,
					number_format( $over_by, 2 ),
					number_format( $projected, 2 ),
					number_format( (float) $client->contract_hours, 2 )
				);
			}
		}

		/* ---- decide what the calendar must do, before touching the row ---- */
		$cal_before = $before ? $this->status_holds_calendar( $before->status ) : false;
		$cal_after  = $this->status_holds_calendar( $status );
		$moved      = ! $before
			|| $before->booking_date !== $date
			|| substr( $before->start_time, 0, 5 ) !== $start
			|| abs( (float) $before->duration_hours - $duration ) > 0.001
			|| (string) $before->notes !== (string) $notes;
		$touch_cal  = ( $cal_before !== $cal_after ) || ( $cal_after && $moved );
		if ( $opts['calendar_recreate'] && $cal_after ) {
			$touch_cal = true; // S28: the event was deleted out from under a live row.
		}
		// S28: which of the two pushes actually fire. Everything above this line
		// behaves identically whichever way these resolve.
		$push_remove = $opts['push_calendar'] && $touch_cal && $cal_before && ! $opts['calendar_recreate'];
		$push_create = $opts['push_calendar'] && $touch_cal && $cal_after;

		$label = $this->booking_client_label( $client_id, $before );
		$email = $this->booking_client_email( $client_id, $before );

		// 1 of 3 — remove the OLD calendar event under its OLD idempotency id.
		// The marker in client_name keeps the machine's Slack alert honest: a move
		// is not a cancellation and must not read like one.
		if ( $push_remove ) {
			$this->push_booking_event(
				'booking_cancelled',
				array(
					'booking_id'   => $this->event_bid( $before ),
					'client_name'  => $label . ( $cal_after ? ' (admin edit — moving)' : ' (cancelled in wp-admin)' ),
					'client_email' => $email,
					'date'         => $before->booking_date,
					'start_time'   => substr( $before->start_time, 0, 5 ),
					'end_time'     => substr( $before->end_time, 0, 5 ),
				)
			);
		}

		/* ---- 2 of 3 — write the row (this IS the ledger move) ---- */
		$new_rc = $before ? (int) $before->reschedule_count : 0;
		if ( $before && $push_create ) {
			$new_rc++; // fresh idempotency id for the machine, fresh SEQUENCE for .ics
		}

		$row = array(
			'booking_date'     => $date,
			'start_time'       => $start_sql,
			'end_time'         => $end_sql,
			'duration_hours'   => $duration,
			'status'           => $status,
			'notes'            => $notes,
			'reschedule_count' => $new_rc,
		);
		$fmt = array( '%s', '%s', '%s', '%f', '%s', '%s', '%d' );

		if ( in_array( $status, array( 'cancelled', 'cancelled_late' ), true ) ) {
			$row['cancelled_at'] = current_time( 'mysql' );
			$fmt[]               = '%s';
		} elseif ( $before && ! empty( $before->cancelled_at ) ) {
			$row['cancelled_at'] = null; // un-cancelled: don't leave a stale timestamp behind
			$fmt[]               = '%s';
		}

		if ( $before ) {
			$ok = false !== $wpdb->update( $this->bookings_table, $row, array( 'id' => $booking_id ), $fmt, array( '%d' ) );
		} else {
			$row['client_id']  = $client_id;
			$fmt[]             = '%d';
			$row['created_at'] = current_time( 'mysql' );
			$fmt[]             = '%s';
			$ok                = (bool) $wpdb->insert( $this->bookings_table, $row, $fmt );
			$booking_id        = $wpdb->insert_id;
		}

		if ( ! $ok ) {
			// The old calendar event is already gone at this point; say so rather
			// than leaving Michael to discover it.
			return array(
				'ok'         => false,
				'booking_id' => $booking_id,
				'message'    => __( 'The database write failed. If this was an edit, the old calendar event was already removed — re-save the booking to put it back.', 'mwm-studio' ),
				'warnings'   => $warnings,
			);
		}

		$this->clear_rental_day_cache( $date );
		if ( $before && $before->booking_date !== $date ) {
			$this->clear_rental_day_cache( $before->booking_date );
		}

		// 3 of 3 — create the NEW calendar event under a fresh idempotency id.
		if ( $push_create ) {
			$this->push_booking_event(
				'booking_created',
				array(
					'booking_id'   => $this->event_bid( (object) array( 'id' => $booking_id, 'reschedule_count' => $new_rc ) ),
					'client_name'  => $label,
					'client_email' => $email,
					'date'         => $date,
					'start_time'   => $start,
					'end_time'     => substr( $end_sql, 0, 5 ),
					'duration'     => $duration,
					'notes'        => $notes ? $notes : ( $before ? 'Adjusted in wp-admin' : 'Created in wp-admin' ),
				)
			);
		}

		/* ---- audit ---- */
		$snap = function ( $b ) {
			if ( ! $b ) {
				return null;
			}
			return array(
				'date'     => $b->booking_date,
				'start'    => substr( $b->start_time, 0, 5 ),
				'end'      => substr( $b->end_time, 0, 5 ),
				'duration' => (float) $b->duration_hours,
				'status'   => $b->status,
				'notes'    => (string) $b->notes,
			);
		};
		$this->audit_log(
			$opts['action'] ? $opts['action'] : ( $before ? 'booking.edit' : 'booking.create' ),
			$booking_id,
			$client_id,
			$snap( $before ),
			array(
				'date'     => $date,
				'start'    => $start,
				'end'      => substr( $end_sql, 0, 5 ),
				'duration' => $duration,
				'status'   => $status,
				'notes'    => $notes,
			),
			$opts['reason'],
			$opts['actor']
		);

		/* ---- loud flag when the client is past their contract total ---- */
		if ( $over_by > 0 && $client ) {
			$this->notify_admin(
				sprintf( '[MWM Studio] %s is OVER contract by %s h', $client->name, number_format( $over_by, 2 ) ),
				sprintf(
					"Booking #%d (%s %s, %sh, %s) puts %s past their contract total of %s hours by %s.\n\nThis was allowed on purpose — the booking is saved. Decide whether to add hours to the package or bill the overage.\n\nClients screen: %s",
					$booking_id,
					$date,
					$start,
					$duration,
					$status,
					$client->name,
					number_format( (float) $client->contract_hours, 2 ),
					number_format( $over_by, 2 ),
					admin_url( 'admin.php?page=mwm-studio-clients' )
				)
			);
		}

		/* ---- optional client email (OFF by default: admin edits are silent) ---- */
		if ( $opts['notify_client'] && $email && $cal_after ) {
			$settings = $this->get_settings();
			$html     = $this->get_branded_email_html(
				array(
					'eyebrow'    => $before ? 'Booking Updated' : 'Booking Confirmed',
					'title'      => $before ? 'Your Studio Session Was Updated' : 'Your Studio Session Is Booked',
					'preheader'  => sprintf( 'Your studio session on %s at %s.', date_i18n( 'F j, Y', strtotime( $date ) ), $start ),
					'name'       => $label,
					'intro'      => $before ? 'Your studio session has been updated. Here are the current details:' : 'Your studio session is confirmed. Here are your details:',
					'rows'       => array(
						'Date'     => date_i18n( 'l, F j, Y', strtotime( $date ) ),
						'Time'     => $start . ' – ' . substr( $end_sql, 0, 5 ),
						'Duration' => $duration . ' hour(s)',
						'Location' => $settings['studio_name'] . ', ' . $settings['studio_address'],
					),
					'body_after' => 'This booking appears under <strong>Upcoming Bookings</strong> in your client portal.',
					'cta_label'  => 'Open Your Client Portal',
					'cta_url'    => 'https://mwmcreations.com/studio-portal/',
					'outro'      => 'See you at the studio!',
				)
			);
			$this->notify_client_html_ics(
				$email,
				sprintf( '%s — %s at %s | %s', $before ? 'Booking updated' : 'Booking confirmed', $date, $start, $settings['studio_name'] ),
				$html,
				(object) array(
					'id'               => $booking_id,
					'booking_date'     => $date,
					'start_time'       => $start_sql,
					'end_time'         => $end_sql,
					'is_rental'        => $is_rental,
					'reschedule_count' => $new_rc,
					'guest_email'      => $email,
					'created_at'       => '',
				)
			);
		}

		return array(
			'ok'         => true,
			'booking_id' => $booking_id,
			'message'    => $before
				? sprintf( __( 'Booking #%d updated.', 'mwm-studio' ), $booking_id )
				: sprintf( __( 'Booking #%d created.', 'mwm-studio' ), $booking_id ),
			'warnings'   => $warnings,
		);
	}

	/** S26: does this booking's date fall inside the client's contract window? */
	private function booking_in_contract( $booking, $client ) {
		if ( empty( $client->contract_start_date ) || empty( $client->contract_end_date ) ) {
			return true; // no window set: hours_used_in_contract() sums everything
		}
		$d = $booking->booking_date;
		return ( $d >= $client->contract_start_date && $d <= $client->contract_end_date );
	}

	/* ---- POST handlers ------------------------------------------------- */

	private function admin_save_booking() {
		$id     = isset( $_POST['booking_id'] ) ? (int) $_POST['booking_id'] : 0;
		$fields = array(
			'booking_date'   => isset( $_POST['booking_date'] ) ? sanitize_text_field( wp_unslash( $_POST['booking_date'] ) ) : '',
			'start_time'     => isset( $_POST['start_time'] ) ? sanitize_text_field( wp_unslash( $_POST['start_time'] ) ) : '',
			'duration_hours' => isset( $_POST['duration_hours'] ) ? (float) $_POST['duration_hours'] : 0,
			'status'         => isset( $_POST['status'] ) ? sanitize_text_field( wp_unslash( $_POST['status'] ) ) : 'confirmed',
			'notes'          => isset( $_POST['notes'] ) ? sanitize_textarea_field( wp_unslash( $_POST['notes'] ) ) : '',
		);
		if ( ! $id ) {
			$fields['client_id'] = isset( $_POST['client_id'] ) ? (int) $_POST['client_id'] : 0;
		}

		$repeat = isset( $_POST['repeat_weekly'] ) ? max( 0, min( 25, (int) $_POST['repeat_weekly'] ) ) : 0;
		$opts   = array(
			'reason'         => isset( $_POST['reason'] ) ? sanitize_text_field( wp_unslash( $_POST['reason'] ) ) : '',
			'notify_client'  => ! empty( $_POST['notify_client'] ),
			'allow_conflict' => ! empty( $_POST['allow_conflict'] ),
		);

		$results  = array();
		$warnings = array();
		$failed   = '';

		$res = $this->admin_write_booking( $id, $fields, $opts );
		if ( ! $res['ok'] ) {
			set_transient( 'mwm_studio_admin_error', $res['message'], 60 );
			wp_safe_redirect( admin_url( 'admin.php?page=mwm-studio-booking-edit' . ( $id ? '&id=' . $id : '' ) ) );
			exit;
		}
		$results[] = $res['booking_id'];
		$warnings  = array_merge( $warnings, $res['warnings'] );

		// Weekly repeat — same weekday, same time, N further weeks. Created one at a
		// time through the same write path, so each gets its own row, calendar event
		// and audit entry. A failure stops the run and says which week it stopped on.
		if ( ! $id && $repeat > 0 ) {
			for ( $w = 1; $w <= $repeat; $w++ ) {
				$next          = date( 'Y-m-d', strtotime( $fields['booking_date'] . ' +' . ( 7 * $w ) . ' days' ) );
				$more          = $fields;
				$more['booking_date'] = $next;
				$r             = $this->admin_write_booking( 0, $more, $opts );
				if ( ! $r['ok'] ) {
					$failed = sprintf( __( 'Stopped at %s: %s', 'mwm-studio' ), $next, $r['message'] );
					break;
				}
				$results[] = $r['booking_id'];
				$warnings  = array_merge( $warnings, $r['warnings'] );
			}
		}

		set_transient( 'mwm_studio_admin_notice', array( 'ids' => $results, 'warnings' => $warnings, 'failed' => $failed ), 60 );
		wp_safe_redirect( admin_url( 'admin.php?page=mwm-studio-bookings&saved=1' ) );
		exit;
	}

	private function admin_adjust_hours() {
		global $wpdb;
		$id = isset( $_POST['client_id'] ) ? (int) $_POST['client_id'] : 0;
		$c  = $id ? $this->get_client( $id ) : null;
		if ( ! $c ) {
			set_transient( 'mwm_studio_admin_error', __( 'Client not found.', 'mwm-studio' ), 60 );
			wp_safe_redirect( admin_url( 'admin.php?page=mwm-studio-clients' ) );
			exit;
		}

		$mode  = isset( $_POST['hours_mode'] ) ? sanitize_text_field( wp_unslash( $_POST['hours_mode'] ) ) : 'add';
		$value = isset( $_POST['hours_value'] ) ? (float) $_POST['hours_value'] : 0;
		$old   = (float) $c->contract_hours;
		$new   = ( 'set' === $mode ) ? $value : $old + $value;

		if ( $new < 0 || $new > 999 ) {
			set_transient( 'mwm_studio_admin_error', __( 'Contract total must be between 0 and 999 hours.', 'mwm-studio' ), 60 );
			wp_safe_redirect( admin_url( 'admin.php?page=mwm-studio-clients' ) );
			exit;
		}

		$wpdb->update(
			$this->clients_table,
			array( 'contract_hours' => $new, 'updated_at' => current_time( 'mysql' ) ),
			array( 'id' => $id ),
			array( '%f', '%s' ),
			array( '%d' )
		);

		$this->audit_log(
			'client.hours_adjust',
			0,
			$id,
			array( 'contract_hours' => $old ),
			array( 'contract_hours' => $new ),
			isset( $_POST['reason'] ) ? sanitize_text_field( wp_unslash( $_POST['reason'] ) ) : ''
		);

		set_transient(
			'mwm_studio_admin_notice',
			array(
				'ids'      => array(),
				'warnings' => array( sprintf( __( '%1$s: contract total %2$s → %3$s hours.', 'mwm-studio' ), $c->name, number_format( $old, 2 ), number_format( $new, 2 ) ) ),
				'failed'   => '',
			),
			60
		);
		wp_safe_redirect( admin_url( 'admin.php?page=mwm-studio-clients' ) );
		exit;
	}

	/* ---- Screens -------------------------------------------------------- */

	/** S26: shared notice renderer for the admin screens. */
	private function print_admin_notice() {
		if ( $err = get_transient( 'mwm_studio_admin_error' ) ) {
			delete_transient( 'mwm_studio_admin_error' );
			echo '<div class="notice notice-error is-dismissible"><p>' . esc_html( $err ) . '</p></div>';
		}
		$n = get_transient( 'mwm_studio_admin_notice' );
		if ( ! $n ) {
			return;
		}
		delete_transient( 'mwm_studio_admin_notice' );
		if ( ! empty( $n['ids'] ) ) {
			echo '<div class="notice notice-success is-dismissible"><p>'
				. esc_html( sprintf( _n( 'Booking #%s saved.', 'Bookings #%s saved.', count( $n['ids'] ), 'mwm-studio' ), implode( ', #', array_map( 'intval', $n['ids'] ) ) ) )
				. '</p></div>';
		}
		foreach ( (array) $n['warnings'] as $w ) {
			echo '<div class="notice notice-warning is-dismissible"><p>' . esc_html( $w ) . '</p></div>';
		}
		if ( ! empty( $n['failed'] ) ) {
			echo '<div class="notice notice-error is-dismissible"><p>' . esc_html( $n['failed'] ) . '</p></div>';
		}
	}

	public function render_booking_edit_page() {
		global $wpdb;
		$id = isset( $_GET['id'] ) ? (int) $_GET['id'] : 0;
		$b  = $id ? $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->bookings_table} WHERE id = %d", $id ) ) : null;
		if ( $id && ! $b ) {
			echo '<div class="wrap"><h1>' . esc_html__( 'Booking not found', 'mwm-studio' ) . '</h1></div>';
			return;
		}
		$clients   = $wpdb->get_results( "SELECT id, name, contract_hours, contract_start_date, contract_end_date FROM {$this->clients_table} WHERE active = 1 ORDER BY name ASC" );
		$pre_client = isset( $_GET['client_id'] ) ? (int) $_GET['client_id'] : ( $b ? (int) $b->client_id : 0 );
		$this->print_admin_notice();
		?>
		<div class="wrap mwm-studio-admin">
			<h1><?php echo $b ? esc_html( sprintf( __( 'Edit Booking #%d', 'mwm-studio' ), $id ) ) : esc_html__( 'Add Booking', 'mwm-studio' ); ?></h1>
			<p style="max-width:640px;color:#555;">
				<?php esc_html_e( 'Saving here writes the booking, moves the client\'s hours, and updates the Google Calendar event in one operation. The three cannot drift apart.', 'mwm-studio' ); ?>
			</p>

			<form method="post" class="mwm-card" style="max-width:640px;">
				<?php wp_nonce_field( 'mwm_studio_save_booking' ); ?>
				<input type="hidden" name="mwm_studio_action" value="save_booking" />
				<input type="hidden" name="booking_id" value="<?php echo esc_attr( $id ); ?>" />

				<p><label><strong><?php esc_html_e( 'Client', 'mwm-studio' ); ?></strong></label><br />
				<?php if ( $b && ! $b->client_id ) : ?>
					<input type="text" class="widefat" value="<?php echo esc_attr( $b->guest_name . ' (rental — ' . $b->guest_email . ')' ); ?>" disabled />
					<small style="color:#666;"><?php esc_html_e( 'This is a paid rental. The client cannot be changed.', 'mwm-studio' ); ?></small>
				<?php elseif ( $b ) : ?>
					<input type="text" class="widefat" value="<?php echo esc_attr( $this->booking_client_label( (int) $b->client_id, $b ) ); ?>" disabled />
					<small style="color:#666;"><?php esc_html_e( 'To move a booking to a different client, cancel it and create a new one.', 'mwm-studio' ); ?></small>
				<?php else : ?>
					<select name="client_id" class="widefat" required>
						<option value=""><?php esc_html_e( '— pick a client —', 'mwm-studio' ); ?></option>
						<?php foreach ( $clients as $c ) : ?>
							<option value="<?php echo esc_attr( $c->id ); ?>" <?php selected( $pre_client, $c->id ); ?>>
								<?php
								$used = $this->hours_used_in_contract( $c->id, $c->contract_start_date, $c->contract_end_date );
								echo esc_html( sprintf( '%s — %s / %s h used', $c->name, number_format( $used, 1 ), number_format( $c->contract_hours, 1 ) ) );
								?>
							</option>
						<?php endforeach; ?>
					</select>
				<?php endif; ?>
				</p>

				<p style="display:flex;gap:12px;flex-wrap:wrap;">
					<span style="flex:1 1 180px;"><label><strong><?php esc_html_e( 'Date', 'mwm-studio' ); ?></strong></label><br />
					<input type="date" name="booking_date" class="widefat" required value="<?php echo esc_attr( $b ? $b->booking_date : '' ); ?>" /></span>

					<span style="flex:1 1 140px;"><label><strong><?php esc_html_e( 'Start time', 'mwm-studio' ); ?></strong></label><br />
					<input type="time" name="start_time" class="widefat" required step="300" value="<?php echo esc_attr( $b ? substr( $b->start_time, 0, 5 ) : '' ); ?>" /></span>

					<span style="flex:1 1 140px;"><label><strong><?php esc_html_e( 'Duration (hours)', 'mwm-studio' ); ?></strong></label><br />
					<input type="number" name="duration_hours" class="widefat" required min="0.25" max="12" step="0.25" value="<?php echo esc_attr( $b ? rtrim( rtrim( number_format( (float) $b->duration_hours, 2, '.', '' ), '0' ), '.' ) : '1' ); ?>" />
					<small style="color:#666;"><?php esc_html_e( 'Any quarter hour. 1.5 is as easy as 1.', 'mwm-studio' ); ?></small></span>
				</p>

				<p><label><strong><?php esc_html_e( 'Status', 'mwm-studio' ); ?></strong></label><br />
				<select name="status" class="widefat">
					<?php
					$labels = array(
						'confirmed'      => __( 'Confirmed — holds the studio, counts hours', 'mwm-studio' ),
						'completed'      => __( 'Completed — happened, counts hours', 'mwm-studio' ),
						'cancelled'      => __( 'Cancelled — hours returned, calendar event removed', 'mwm-studio' ),
						'cancelled_late' => __( 'Cancelled late — hours forfeited, calendar event removed', 'mwm-studio' ),
					);
					$cur    = $b ? $b->status : 'confirmed';
					foreach ( $labels as $k => $v ) :
						?>
						<option value="<?php echo esc_attr( $k ); ?>" <?php selected( $cur, $k ); ?>><?php echo esc_html( $v ); ?></option>
					<?php endforeach; ?>
				</select></p>

				<p><label><strong><?php esc_html_e( 'Notes', 'mwm-studio' ); ?></strong></label><br />
				<textarea name="notes" class="widefat" rows="2"><?php echo esc_textarea( $b ? (string) $b->notes : '' ); ?></textarea></p>

				<?php if ( ! $b ) : ?>
					<p><label><strong><?php esc_html_e( 'Repeat weekly', 'mwm-studio' ); ?></strong></label><br />
					<input type="number" name="repeat_weekly" min="0" max="25" step="1" value="0" style="width:90px;" />
					<small style="color:#666;"><?php esc_html_e( 'extra weeks after this one, same weekday and time (0 = just this one)', 'mwm-studio' ); ?></small></p>
				<?php endif; ?>

				<p><label><strong><?php esc_html_e( 'Reason (kept in the audit trail)', 'mwm-studio' ); ?></strong></label><br />
				<input type="text" name="reason" class="widefat" placeholder="<?php esc_attr_e( 'e.g. ran 30 minutes over', 'mwm-studio' ); ?>" /></p>

				<p><label><input type="checkbox" name="notify_client" value="1" /> <?php esc_html_e( 'Email the client a confirmation', 'mwm-studio' ); ?></label><br />
				<small style="color:#666;"><?php esc_html_e( 'Off by default — admin changes are silent so you can send one message yourself.', 'mwm-studio' ); ?></small></p>

				<p><label><input type="checkbox" name="allow_conflict" value="1" /> <?php esc_html_e( 'Allow this even if it overlaps another booking', 'mwm-studio' ); ?></label></p>

				<p>
					<button class="button button-primary"><?php echo $b ? esc_html__( 'Save Booking', 'mwm-studio' ) : esc_html__( 'Create Booking', 'mwm-studio' ); ?></button>
					<a class="button" href="<?php echo esc_url( admin_url( 'admin.php?page=mwm-studio-bookings' ) ); ?>"><?php esc_html_e( 'Cancel', 'mwm-studio' ); ?></a>
				</p>
			</form>

			<?php if ( $id ) : ?>
				<?php
				$hist = $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$this->audit_table} WHERE booking_id = %d ORDER BY id DESC LIMIT 25", $id ) );
				if ( $hist ) :
					?>
					<h2 style="margin-top:28px;"><?php esc_html_e( 'History', 'mwm-studio' ); ?></h2>
					<table class="widefat striped" style="max-width:900px;">
						<thead><tr>
							<th><?php esc_html_e( 'When', 'mwm-studio' ); ?></th>
							<th><?php esc_html_e( 'Who', 'mwm-studio' ); ?></th>
							<th><?php esc_html_e( 'Action', 'mwm-studio' ); ?></th>
							<th><?php esc_html_e( 'Before', 'mwm-studio' ); ?></th>
							<th><?php esc_html_e( 'After', 'mwm-studio' ); ?></th>
							<th><?php esc_html_e( 'Reason', 'mwm-studio' ); ?></th>
						</tr></thead>
						<tbody>
						<?php foreach ( $hist as $h ) : ?>
							<tr>
								<td><?php echo esc_html( date_i18n( 'M j, Y g:i a', strtotime( $h->created_at ) ) ); ?></td>
								<td><?php echo esc_html( $h->actor_name ); ?></td>
								<td><code><?php echo esc_html( $h->action ); ?></code></td>
								<td><small><?php echo esc_html( $this->audit_summary( $h->before_json ) ); ?></small></td>
								<td><small><?php echo esc_html( $this->audit_summary( $h->after_json ) ); ?></small></td>
								<td><small><?php echo esc_html( $h->reason ); ?></small></td>
							</tr>
						<?php endforeach; ?>
						</tbody>
					</table>
				<?php endif; ?>
			<?php endif; ?>
		</div>
		<?php
		$this->print_admin_css();
	}

	/** S26: one-line rendering of an audit snapshot. */
	private function audit_summary( $json ) {
		if ( ! $json ) {
			return '—';
		}
		$d = json_decode( $json, true );
		if ( ! is_array( $d ) ) {
			return '—';
		}
		if ( array_key_exists( 'contract_hours', $d ) ) {
			return number_format( (float) $d['contract_hours'], 2 ) . ' h total';
		}
		return sprintf(
			'%s %s–%s · %sh · %s',
			isset( $d['date'] ) ? $d['date'] : '?',
			isset( $d['start'] ) ? $d['start'] : '?',
			isset( $d['end'] ) ? $d['end'] : '?',
			isset( $d['duration'] ) ? $d['duration'] : '?',
			isset( $d['status'] ) ? $d['status'] : '?'
		);
	}

	/**
	 * S26: reconciliation check — flags any booking whose row has no matching
	 * block on the MWM CREATIONS calendar.
	 *
	 * It compares against the SAME /studio-availability feed the portal uses for
	 * slots, so there is no second view of the calendar to drift. The feed gives
	 * anonymous busy blocks, not event ids — so this answers "does a calendar
	 * block exist with exactly this start and end?", which is precisely the
	 * question that would have caught #61 before the client did.
	 */
	public function render_reconcile_page() {
		global $wpdb;
		$from = isset( $_GET['from'] ) ? sanitize_text_field( wp_unslash( $_GET['from'] ) ) : date( 'Y-m-d', strtotime( current_time( 'Y-m-d' ) . ' -30 days' ) );
		$to   = isset( $_GET['to'] ) ? sanitize_text_field( wp_unslash( $_GET['to'] ) ) : date( 'Y-m-d', strtotime( current_time( 'Y-m-d' ) . ' +90 days' ) );
		if ( ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', $from ) ) {
			$from = current_time( 'Y-m-d' );
		}
		if ( ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', $to ) ) {
			$to = current_time( 'Y-m-d' );
		}

		// S27: one implementation, shared with the daily drift cron.
		$drift   = $this->find_calendar_drift( $from, $to );
		$checked = $drift['checked'];
		$unknown = $drift['unknown'];
		$bad     = $drift['bad'];
		?>
		<div class="wrap mwm-studio-admin">
			<h1><?php esc_html_e( 'Booking ↔ Calendar Reconciliation', 'mwm-studio' ); ?></h1>
			<form method="get" class="mwm-filters">
				<input type="hidden" name="page" value="mwm-studio-reconcile" />
				<label><?php esc_html_e( 'From', 'mwm-studio' ); ?> <input type="date" name="from" value="<?php echo esc_attr( $from ); ?>" /></label>
				<label><?php esc_html_e( 'To', 'mwm-studio' ); ?> <input type="date" name="to" value="<?php echo esc_attr( $to ); ?>" /></label>
				<button class="button"><?php esc_html_e( 'Check', 'mwm-studio' ); ?></button>
			</form>

			<p><strong><?php echo esc_html( sprintf( __( '%1$d bookings checked · %2$d disagree with the calendar', 'mwm-studio' ), $checked, count( $bad ) ) ); ?></strong>
			<?php if ( $unknown ) : ?>
				<br /><span style="color:#c62828;"><?php echo esc_html( sprintf( __( '%d could not be checked — the availability feed was unreachable for those dates.', 'mwm-studio' ), $unknown ) ); ?></span>
			<?php endif; ?>
			</p>

			<?php if ( ! $bad && $checked ) : ?>
				<div class="notice notice-success inline"><p><?php esc_html_e( 'Every booking has a calendar block with exactly its start and end time.', 'mwm-studio' ); ?></p></div>
			<?php elseif ( $bad ) : ?>
				<table class="widefat striped" style="max-width:1000px;">
					<thead><tr>
						<th>#</th>
						<th><?php esc_html_e( 'Client', 'mwm-studio' ); ?></th>
						<th><?php esc_html_e( 'Booking row says', 'mwm-studio' ); ?></th>
						<th><?php esc_html_e( 'Calendar has', 'mwm-studio' ); ?></th>
						<th></th>
					</tr></thead>
					<tbody>
					<?php foreach ( $bad as $x ) : $r = $x['b']; ?>
						<tr>
							<td><?php echo esc_html( $r->id ); ?></td>
							<td><?php echo esc_html( $r->client_name ? $r->client_name : ( $r->guest_name . ' (rental)' ) ); ?></td>
							<td><strong><?php echo esc_html( $r->booking_date . ' ' . substr( $r->start_time, 0, 5 ) . '–' . substr( $r->end_time, 0, 5 ) ); ?></strong></td>
							<td><?php echo esc_html( $x['near'] ? implode( ', ', $x['near'] ) : __( 'nothing overlapping — no event at all', 'mwm-studio' ) ); ?></td>
							<td><a class="button button-small" href="<?php echo esc_url( admin_url( 'admin.php?page=mwm-studio-booking-edit&id=' . $r->id ) ); ?>"><?php esc_html_e( 'Open', 'mwm-studio' ); ?></a></td>
						</tr>
					<?php endforeach; ?>
					</tbody>
				</table>
				<p style="color:#555;max-width:720px;">
					<?php esc_html_e( 'Re-saving a flagged booking from its edit screen removes the stale calendar event and writes a fresh one that matches the row. The row is the source of truth.', 'mwm-studio' ); ?>
				</p>
			<?php endif; ?>
		</div>
		<?php
		$this->print_admin_css();
	}

	/** S26: the full audit trail, newest first. */
	public function render_audit_page() {
		global $wpdb;
		$rows = $wpdb->get_results( "SELECT * FROM {$this->audit_table} ORDER BY id DESC LIMIT 200" );
		?>
		<div class="wrap mwm-studio-admin">
			<h1><?php esc_html_e( 'Studio Audit Trail', 'mwm-studio' ); ?></h1>
			<table class="widefat striped">
				<thead><tr>
					<th><?php esc_html_e( 'When', 'mwm-studio' ); ?></th>
					<th><?php esc_html_e( 'Who', 'mwm-studio' ); ?></th>
					<th><?php esc_html_e( 'Action', 'mwm-studio' ); ?></th>
					<th><?php esc_html_e( 'Booking', 'mwm-studio' ); ?></th>
					<th><?php esc_html_e( 'Before', 'mwm-studio' ); ?></th>
					<th><?php esc_html_e( 'After', 'mwm-studio' ); ?></th>
					<th><?php esc_html_e( 'Reason', 'mwm-studio' ); ?></th>
				</tr></thead>
				<tbody>
				<?php if ( $rows ) : ?>
					<?php foreach ( $rows as $h ) : ?>
						<tr>
							<td><?php echo esc_html( date_i18n( 'M j, Y g:i a', strtotime( $h->created_at ) ) ); ?></td>
							<td><?php echo esc_html( $h->actor_name ); ?></td>
							<td><code><?php echo esc_html( $h->action ); ?></code></td>
							<td><?php echo $h->booking_id ? '<a href="' . esc_url( admin_url( 'admin.php?page=mwm-studio-booking-edit&id=' . (int) $h->booking_id ) ) . '">#' . esc_html( $h->booking_id ) . '</a>' : '—'; ?></td>
							<td><small><?php echo esc_html( $this->audit_summary( $h->before_json ) ); ?></small></td>
							<td><small><?php echo esc_html( $this->audit_summary( $h->after_json ) ); ?></small></td>
							<td><small><?php echo esc_html( $h->reason ); ?></small></td>
						</tr>
					<?php endforeach; ?>
				<?php else : ?>
					<tr><td colspan="7"><?php esc_html_e( 'Nothing recorded yet.', 'mwm-studio' ); ?></td></tr>
				<?php endif; ?>
				</tbody>
			</table>
		</div>
		<?php
		$this->print_admin_css();
	}


	/* =========================================================================
	 * S27 — QUICK BOOK (phone) + DRIFT WATCH (Aug 13 2026, Michael)
	 *
	 * Michael: *"most of the time I'm on my phone… going to WordPress through my
	 * phone is not very convenient."*
	 *
	 * A client asks him in the studio to book an hour. He should not have to log
	 * into wp-admin on a phone to do it. So this is a STANDALONE page —
	 * /studio-quick-book/ — outside wp-admin entirely: no WordPress login, no
	 * menus, no admin chrome. He adds it to his home screen once and it opens
	 * like an app.
	 *
	 * 🔴 It creates bookings through admin_write_booking() — the same single
	 * write path as the admin screens. It is a new DOOR, not a new write path.
	 * That distinction is the whole lesson of #61.
	 *
	 * AUTH, since there is no WordPress session:
	 *   1. a long random token in the URL (?k=…), compared with hash_equals —
	 *      the same pattern the /manage-booking/ magic link already uses;
	 *   2. a 4-digit PIN that MICHAEL sets himself on first open. Only its hash
	 *      is stored — DEV never sees or handles the value.
	 * A pass sets a signed cookie good for 7 days, so it asks about once a week.
	 * PIN attempts are rate limited. Losing the phone costs one token rotation.
	 *
	 * What it deliberately CANNOT do: cancel a booking, change anyone's hours,
	 * edit a client, or show money. It creates a booking for a client who
	 * already exists. Anything destructive stays behind a real wp-admin login.
	 * ========================================================================= */

	/** S27: the secret in the quick-book URL. Generated on demand, rotatable. */
	private function qb_token( $create = true ) {
		$t = get_option( 'mwm_studio_qb_token' );
		if ( ! $t && $create ) {
			$t = wp_generate_password( 48, false, false );
			update_option( 'mwm_studio_qb_token', $t, false );
		}
		return $t ? $t : '';
	}

	private function qb_url() {
		return home_url( '/studio-quick-book/' ) . '?k=' . rawurlencode( $this->qb_token() );
	}

	/** S27: constant-time check of the ?k= token. */
	private function qb_token_ok() {
		$given = isset( $_REQUEST['k'] ) ? sanitize_text_field( wp_unslash( $_REQUEST['k'] ) ) : '';
		$real  = $this->qb_token( false );
		return ( $real && strlen( $given ) === strlen( $real ) && hash_equals( $real, $given ) );
	}

	private function qb_pin_hash() {
		return (string) get_option( 'mwm_studio_qb_pin', '' );
	}

	/** S27: signed 7-day cookie, bound to the current PIN hash and token. */
	private function qb_cookie_value( $expiry ) {
		return $expiry . '|' . hash_hmac( 'sha256', $expiry . '|' . $this->qb_pin_hash() . '|' . $this->qb_token( false ), wp_salt( 'auth' ) );
	}

	private function qb_cookie_ok() {
		$c = isset( $_COOKIE['mwm_qb'] ) ? sanitize_text_field( wp_unslash( $_COOKIE['mwm_qb'] ) ) : '';
		if ( ! $c || false === strpos( $c, '|' ) ) {
			return false;
		}
		list( $expiry ) = explode( '|', $c, 2 );
		$expiry         = (int) $expiry;
		if ( $expiry < time() ) {
			return false;
		}
		return hash_equals( $this->qb_cookie_value( $expiry ), $c );
	}

	/** S27: crude per-IP throttle so a 4-digit PIN cannot be walked. */
	private function qb_throttle_key() {
		$ip = isset( $_SERVER['REMOTE_ADDR'] ) ? sanitize_text_field( wp_unslash( $_SERVER['REMOTE_ADDR'] ) ) : 'x';
		return 'mwm_qb_fail_' . md5( $ip );
	}

	/**
	 * S27: PIN set / PIN entry, handled on template_redirect because a shortcode
	 * runs after headers are sent and could not set the cookie.
	 */
	public function qb_handle_gate() {
		if ( empty( $_POST['mwm_qb_gate'] ) || ! $this->qb_token_ok() ) {
			return;
		}
		$key   = $this->qb_throttle_key();
		$fails = (int) get_transient( $key );
		if ( $fails >= 5 ) {
			set_transient( 'mwm_qb_msg', __( 'Too many tries. Wait fifteen minutes.', 'mwm-studio' ), 60 );
			wp_safe_redirect( $this->qb_url() );
			exit;
		}

		$pin  = isset( $_POST['pin'] ) ? preg_replace( '/\D/', '', (string) wp_unslash( $_POST['pin'] ) ) : '';
		$have = $this->qb_pin_hash();

		if ( ! $have ) {
			// First open: Michael chooses the PIN. Only the hash is ever stored.
			if ( strlen( $pin ) !== 4 ) {
				set_transient( 'mwm_qb_msg', __( 'Pick exactly four digits.', 'mwm-studio' ), 60 );
				wp_safe_redirect( $this->qb_url() );
				exit;
			}
			update_option( 'mwm_studio_qb_pin', wp_hash_password( $pin ), false );
		} elseif ( ! wp_check_password( $pin, $have ) ) {
			set_transient( $key, $fails + 1, 15 * MINUTE_IN_SECONDS );
			set_transient( 'mwm_qb_msg', __( 'That PIN is not right.', 'mwm-studio' ), 60 );
			wp_safe_redirect( $this->qb_url() );
			exit;
		}

		delete_transient( $key );
		$expiry = time() + 7 * DAY_IN_SECONDS;
		setcookie( 'mwm_qb', $this->qb_cookie_value( $expiry ), $expiry, COOKIEPATH ? COOKIEPATH : '/', COOKIE_DOMAIN, is_ssl(), true );
		wp_safe_redirect( $this->qb_url() );
		exit;
	}

	/** S27: the standalone page, created once like the manage-booking page. */
	public function ensure_quick_book_page() {
		$known = (int) get_option( 'mwm_studio_qb_page_id' );
		if ( $known && get_post( $known ) ) {
			return;
		}
		$existing = get_page_by_path( 'studio-quick-book' );
		if ( $existing ) {
			update_option( 'mwm_studio_qb_page_id', $existing->ID );
			return;
		}
		$pid = wp_insert_post( array(
			'post_title'   => 'Quick Book',
			'post_name'    => 'studio-quick-book',
			'post_type'    => 'page',
			'post_status'  => 'publish',
			'post_content' => '[mwm_quick_book]',
		) );
		if ( $pid && ! is_wp_error( $pid ) ) {
			update_option( 'mwm_studio_qb_page_id', $pid );
			update_option( 'mwm_studio_qb_noindex', 1, false );
		}
	}

	/** S27: keep the quick-book page out of search engines and sitemaps. */
	public function qb_noindex() {
		$pid = (int) get_option( 'mwm_studio_qb_page_id' );
		if ( $pid && is_page( $pid ) ) {
			echo '<meta name="robots" content="noindex,nofollow,noarchive" />' . "\n";
		}
	}

	private function qb_gate_screen( $mode ) {
		$msg = get_transient( 'mwm_qb_msg' );
		if ( $msg ) {
			delete_transient( 'mwm_qb_msg' );
		}
		ob_start();
		?>
		<div class="qb-wrap qb-gate">
			<div class="qb-lock">🎬</div>
			<h1><?php echo 'set' === $mode ? esc_html__( 'Choose a PIN', 'mwm-studio' ) : esc_html__( 'Quick Book', 'mwm-studio' ); ?></h1>
			<p class="qb-sub">
				<?php
				echo 'set' === $mode
					? esc_html__( 'Four digits. You will be asked for it about once a week. Only its fingerprint is stored — nobody can read it back, so pick something you will remember.', 'mwm-studio' )
					: esc_html__( 'Enter your PIN.', 'mwm-studio' );
				?>
			</p>
			<?php if ( $msg ) : ?><p class="qb-err"><?php echo esc_html( $msg ); ?></p><?php endif; ?>
			<form method="post">
				<input type="hidden" name="mwm_qb_gate" value="1" />
				<input type="hidden" name="k" value="<?php echo esc_attr( $this->qb_token( false ) ); ?>" />
				<input class="qb-pin" type="password" name="pin" inputmode="numeric" pattern="[0-9]*" maxlength="4" autocomplete="off" autofocus placeholder="••••" />
				<button class="qb-go" type="submit"><?php echo 'set' === $mode ? esc_html__( 'Set PIN', 'mwm-studio' ) : esc_html__( 'Open', 'mwm-studio' ); ?></button>
			</form>
		</div>
		<?php
		return ob_get_clean();
	}

	/**
	 * S27: render the page as a BARE document, outside the theme.
	 *
	 * Michael asked for something that "opens like an app". Inside the theme it
	 * would inherit the global nav bar, the footer and the site's typography —
	 * a website on a phone, which is the thing he said was inconvenient. This
	 * takes over the response for that one page only and emits a minimal
	 * document with the iOS home-screen meta, so once it is saved to the home
	 * screen it opens full-screen with no browser chrome.
	 */
	public function qb_maybe_standalone() {
		$pid = (int) get_option( 'mwm_studio_qb_page_id' );
		if ( ! $pid || ! is_page( $pid ) ) {
			return;
		}
		nocache_headers();
		if ( ! defined( 'DONOTCACHEPAGE' ) ) {
			define( 'DONOTCACHEPAGE', true ); // S7 lesson: a cached page serves a stale gate
		}
		header( 'X-Robots-Tag: noindex, nofollow', true );
		?><!doctype html>
<html <?php language_attributes(); ?>>
<head>
<meta charset="<?php bloginfo( 'charset' ); ?>" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="robots" content="noindex,nofollow,noarchive" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-title" content="Quick Book" />
<meta name="apple-mobile-web-app-status-bar-style" content="default" />
<meta name="theme-color" content="#ffffff" />
<title><?php esc_html_e( 'Quick Book', 'mwm-studio' ); ?></title>
</head>
<body style="margin:0;background:#fff;">
<?php
		echo $this->render_quick_book(); // phpcs:ignore WordPress.Security.EscapeOutput
		?>
</body>
</html>
		<?php
		exit;
	}

	public function render_quick_book( $atts = array() ) {
		if ( ! $this->qb_token_ok() ) {
			// Don't confirm the page exists to someone without the link.
			return '<div class="qb-wrap"><h1>Not found</h1></div>' . $this->qb_css();
		}
		if ( ! $this->qb_pin_hash() ) {
			return $this->qb_gate_screen( 'set' ) . $this->qb_css();
		}
		if ( ! $this->qb_cookie_ok() ) {
			return $this->qb_gate_screen( 'enter' ) . $this->qb_css();
		}

		global $wpdb;
		$settings = $this->get_settings();
		$clients  = $wpdb->get_results( "SELECT id, name, contract_hours, contract_start_date, contract_end_date FROM {$this->clients_table} WHERE active = 1 ORDER BY name ASC" );
		$out      = array();
		$today    = current_time( 'Y-m-d' );
		foreach ( $clients as $c ) {
			$used = $this->hours_used_in_contract( $c->id, $c->contract_start_date, $c->contract_end_date );
			$out[] = array(
				'id'        => (int) $c->id,
				'name'      => $c->name,
				'left'      => round( (float) $c->contract_hours - $used, 2 ),
				'total'     => (float) $c->contract_hours,
				'expired'   => ( $c->contract_end_date && $today > $c->contract_end_date ),
				'ends'      => $c->contract_end_date ? $c->contract_end_date : '',
			);
		}

		ob_start();
		?>
		<div class="qb-wrap" id="qb-app"
			data-k="<?php echo esc_attr( $this->qb_token( false ) ); ?>"
			data-ajax="<?php echo esc_url( admin_url( 'admin-ajax.php' ) ); ?>"
			data-clients="<?php echo esc_attr( wp_json_encode( $out ) ); ?>"
			data-today="<?php echo esc_attr( $today ); ?>">

			<header class="qb-head"><span class="qb-dot">🎬</span> <?php echo esc_html( $settings['studio_name'] ); ?> — <?php esc_html_e( 'Quick Book', 'mwm-studio' ); ?></header>

			<section class="qb-step" id="qb-step-who">
				<h2><?php esc_html_e( 'Who', 'mwm-studio' ); ?></h2>
				<div class="qb-clients" id="qb-clients"></div>
			</section>

			<section class="qb-step qb-hidden" id="qb-step-when">
				<h2><?php esc_html_e( 'When', 'mwm-studio' ); ?></h2>
				<div class="qb-days" id="qb-days"></div>
			</section>

			<section class="qb-step qb-hidden" id="qb-step-long">
				<h2><?php esc_html_e( 'How long', 'mwm-studio' ); ?></h2>
				<div class="qb-dur">
					<button type="button" class="qb-step-btn" id="qb-minus">−</button>
					<span id="qb-dur-label">1 h</span>
					<button type="button" class="qb-step-btn" id="qb-plus">+</button>
				</div>
			</section>

			<section class="qb-step qb-hidden" id="qb-step-time">
				<h2><?php esc_html_e( 'What time', 'mwm-studio' ); ?></h2>
				<div class="qb-note qb-hidden" id="qb-time-note"></div>
				<div class="qb-slots" id="qb-slots"></div>
				<div class="qb-other">
					<label><?php esc_html_e( 'Other time', 'mwm-studio' ); ?>
						<input type="time" id="qb-custom" step="900" />
					</label>
				</div>
			</section>

			<section class="qb-step qb-hidden" id="qb-step-go">
				<label class="qb-check"><input type="checkbox" id="qb-notify" checked /> <?php esc_html_e( 'Email them a confirmation', 'mwm-studio' ); ?></label>
				<div class="qb-summary" id="qb-summary"></div>
				<button type="button" class="qb-book" id="qb-book"><?php esc_html_e( 'BOOK IT', 'mwm-studio' ); ?></button>
				<p class="qb-err qb-hidden" id="qb-err"></p>
			</section>

			<section class="qb-done qb-hidden" id="qb-done">
				<div class="qb-tick">✓</div>
				<div id="qb-done-text"></div>
				<button type="button" class="qb-again" id="qb-again"><?php esc_html_e( 'Book another', 'mwm-studio' ); ?></button>
			</section>
		</div>
		<?php
		return ob_get_clean() . $this->qb_css() . $this->qb_js();
	}

	private function qb_css() {
		return <<<'QBCSS'
<style>
#qb-app,.qb-wrap{max-width:520px;margin:0 auto;padding:16px 14px 60px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#14142b;-webkit-text-size-adjust:100%;}
.qb-wrap *{box-sizing:border-box;}
.qb-head{font-weight:700;font-size:15px;color:#6b7280;margin-bottom:18px;}
.qb-dot{font-size:17px;}
.qb-step{margin-bottom:26px;}
.qb-step h2{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#9096a6;margin:0 0 10px;font-weight:700;}
.qb-hidden{display:none!important;}
.qb-clients{display:flex;flex-direction:column;gap:8px;}
.qb-c{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:16px 16px;border:2px solid #e6e7ee;border-radius:14px;background:#fff;font-size:17px;font-weight:600;text-align:left;width:100%;cursor:pointer;line-height:1.25;}
.qb-c small{display:block;font-weight:500;color:#8a90a0;font-size:13px;margin-top:2px;}
.qb-c .qb-left{font-size:14px;font-weight:700;color:#2e7d32;white-space:nowrap;}
.qb-c .qb-left.qb-low{color:#c62828;}
.qb-c.qb-on{border-color:#e05a6d;background:#fff5f6;}
.qb-days{display:flex;gap:8px;overflow-x:auto;padding-bottom:6px;-webkit-overflow-scrolling:touch;}
.qb-d{flex:0 0 auto;width:64px;padding:10px 0;border:2px solid #e6e7ee;border-radius:14px;background:#fff;text-align:center;cursor:pointer;}
.qb-d b{display:block;font-size:20px;line-height:1.1;}
.qb-d span{font-size:11px;color:#8a90a0;text-transform:uppercase;letter-spacing:.06em;}
.qb-d.qb-on{border-color:#e05a6d;background:#fff5f6;}
.qb-dur{display:flex;align-items:center;justify-content:center;gap:22px;}
.qb-dur span{font-size:26px;font-weight:700;min-width:96px;text-align:center;}
.qb-step-btn{width:56px;height:56px;border-radius:50%;border:2px solid #e6e7ee;background:#fff;font-size:26px;line-height:1;cursor:pointer;color:#14142b;}
.qb-slots{display:flex;flex-wrap:wrap;gap:8px;}
.qb-s{padding:14px 18px;border:2px solid #e6e7ee;border-radius:12px;background:#fff;font-size:17px;font-weight:600;cursor:pointer;}
.qb-s.qb-on{border-color:#e05a6d;background:#fff5f6;}
.qb-other{margin-top:14px;font-size:14px;color:#6b7280;}
.qb-other input{margin-left:8px;padding:10px;border:2px solid #e6e7ee;border-radius:10px;font-size:16px;}
.qb-check{display:block;font-size:15px;margin-bottom:14px;}
.qb-check input{margin-right:8px;transform:scale(1.3);}
.qb-summary{font-size:16px;line-height:1.5;background:#f6f7fb;border-radius:14px;padding:14px 16px;margin-bottom:14px;}
.qb-book,.qb-go,.qb-again{width:100%;padding:20px;border:0;border-radius:16px;background:#e05a6d;color:#fff;font-size:19px;font-weight:800;letter-spacing:.04em;cursor:pointer;}
.qb-book[disabled]{opacity:.5;}
.qb-err{color:#c62828;font-weight:600;margin-top:12px;font-size:15px;}
.qb-note{background:#fff7e6;border:1px solid #f0c987;border-radius:12px;padding:10px 12px;font-size:14px;margin-bottom:10px;color:#7a5b16;}
.qb-done{text-align:center;padding-top:40px;}
.qb-tick{font-size:64px;color:#2e7d32;line-height:1;}
.qb-done div{font-size:18px;line-height:1.5;margin:14px 0 22px;}
.qb-gate{text-align:center;padding-top:60px;}
.qb-lock{font-size:52px;}
.qb-gate h1{font-size:24px;margin:12px 0 6px;}
.qb-sub{color:#6b7280;font-size:15px;line-height:1.5;margin-bottom:22px;}
.qb-pin{width:100%;padding:20px;font-size:34px;text-align:center;letter-spacing:.5em;border:2px solid #e6e7ee;border-radius:16px;margin-bottom:14px;}
</style>
QBCSS;
	}

	private function qb_js() {
		return <<<'QBJS'
<script>
(function(){
  var app = document.getElementById('qb-app');
  if (!app) return;
  var K = app.dataset.k, AJAX = app.dataset.ajax;
  var CLIENTS = JSON.parse(app.dataset.clients || '[]');
  var st = { client:null, date:null, dur:1, time:null };
  var $ = function(id){ return document.getElementById(id); };
  function show(id, on){ $(id).classList[on ? 'remove' : 'add']('qb-hidden'); }
  function pad(n){ return n < 10 ? '0'+n : ''+n; }
  function iso(d){ return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate()); }
  function post(action, data){
    var fd = new FormData();
    fd.append('action', action); fd.append('k', K);
    Object.keys(data).forEach(function(x){ fd.append(x, data[x]); });
    return fetch(AJAX, {method:'POST', body:fd, credentials:'same-origin'}).then(function(r){ return r.json(); });
  }
  function durLabel(d){ return (d % 1 === 0 ? d : d.toFixed(2).replace(/0$/,'')) + ' h'; }

  // WHO
  var wrap = $('qb-clients');
  CLIENTS.forEach(function(c){
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'qb-c';
    b.innerHTML = '<span>' + c.name + (c.expired ? '<small>contract ended ' + c.ends + '</small>' : '') + '</span>' +
                  '<span class="qb-left' + (c.left <= 1 ? ' qb-low' : '') + '">' + c.left + ' h left</span>';
    b.addEventListener('click', function(){
      st.client = c;
      Array.prototype.forEach.call(wrap.children, function(x){ x.classList.remove('qb-on'); });
      b.classList.add('qb-on');
      show('qb-step-when', true); show('qb-step-long', true);
      buildDays(); loadSlots();
      $('qb-step-when').scrollIntoView({behavior:'smooth', block:'start'});
    });
    wrap.appendChild(b);
  });

  // WHEN
  function buildDays(){
    var box = $('qb-days'); if (box.children.length) return;
    var base = new Date(app.dataset.today + 'T12:00:00');
    var DOW = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    for (var i = 0; i < 21; i++){
      (function(){
        var d = new Date(base.getTime() + i*86400000);
        var b = document.createElement('button');
        b.type = 'button'; b.className = 'qb-d';
        b.innerHTML = '<b>'+d.getDate()+'</b><span>'+DOW[d.getDay()]+'</span>';
        b.addEventListener('click', function(){
          st.date = iso(d); st.time = null;
          Array.prototype.forEach.call(box.children, function(x){ x.classList.remove('qb-on'); });
          b.classList.add('qb-on');
          loadSlots();
        });
        box.appendChild(b);
      })();
    }
  }

  // HOW LONG
  function setDur(v){
    st.dur = Math.min(8, Math.max(0.5, Math.round(v*4)/4));
    $('qb-dur-label').textContent = durLabel(st.dur);
    st.time = null; loadSlots(); summarise();
  }
  $('qb-minus').addEventListener('click', function(){ setDur(st.dur - 0.25); });
  $('qb-plus').addEventListener('click', function(){ setDur(st.dur + 0.25); });

  // WHAT TIME
  function loadSlots(){
    if (!st.date) { summarise(); return; }
    show('qb-step-time', true);
    var box = $('qb-slots'); box.innerHTML = '<em style="color:#8a90a0">checking…</em>';
    post('mwm_qb_slots', {date: st.date, duration: st.dur}).then(function(res){
      box.innerHTML = '';
      var note = $('qb-time-note');
      if (!res || !res.success) { note.textContent = 'Could not load times — you can still type one below.'; show('qb-time-note', true); summarise(); return; }
      if (res.data.unknown) {
        note.textContent = 'Cannot reach the calendar right now, so these are only checked against bookings. Type a time below if you know it is free.';
        show('qb-time-note', true);
      } else { show('qb-time-note', false); }
      if (!res.data.slots.length) {
        box.innerHTML = '<em style="color:#8a90a0">No open slot that long — try a shorter session or another day, or type a time below.</em>';
      }
      res.data.slots.forEach(function(t){
        var b = document.createElement('button');
        b.type = 'button'; b.className = 'qb-s'; b.textContent = t;
        b.addEventListener('click', function(){
          st.time = t; $('qb-custom').value = '';
          Array.prototype.forEach.call(box.children, function(x){ x.classList && x.classList.remove('qb-on'); });
          b.classList.add('qb-on'); summarise();
        });
        box.appendChild(b);
      });
      summarise();
    });
  }
  $('qb-custom').addEventListener('change', function(){
    st.time = this.value || null;
    Array.prototype.forEach.call($('qb-slots').children, function(x){ x.classList && x.classList.remove('qb-on'); });
    summarise();
  });

  // GO
  function summarise(){
    var ok = st.client && st.date && st.time;
    show('qb-step-go', !!ok);
    if (!ok) return;
    var d = new Date(st.date + 'T12:00:00');
    var days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
    var months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    var after = (st.client.left - st.dur);
    $('qb-summary').innerHTML = '<strong>' + st.client.name + '</strong><br>' +
      days[d.getDay()] + ', ' + months[d.getMonth()] + ' ' + d.getDate() + ' at ' + st.time + '<br>' +
      durLabel(st.dur) + ' — leaves ' + (Math.round(after*100)/100) + ' h' +
      (after < 0 ? ' <strong style="color:#c62828">(over contract)</strong>' : '');
  }

  $('qb-book').addEventListener('click', function(){
    var btn = this; btn.disabled = true; show('qb-err', false);
    post('mwm_qb_create', {
      client_id: st.client.id, date: st.date, start_time: st.time,
      duration: st.dur, notify: $('qb-notify').checked ? 1 : 0
    }).then(function(res){
      btn.disabled = false;
      if (!res || !res.success) {
        $('qb-err').textContent = (res && res.data && res.data.message) ? res.data.message : 'Something went wrong. Try again.';
        show('qb-err', true); return;
      }
      ['qb-step-who','qb-step-when','qb-step-long','qb-step-time','qb-step-go'].forEach(function(x){ show(x, false); });
      $('qb-done-text').innerHTML = res.data.message;
      show('qb-done', true);
      window.scrollTo(0,0);
    }).catch(function(){
      btn.disabled = false;
      $('qb-err').textContent = 'Network error. Try again.'; show('qb-err', true);
    });
  });

  $('qb-again').addEventListener('click', function(){ window.location.reload(); });
})();
</script>
QBJS;
	}

	/* ---- S27 AJAX (token + PIN cookie, no WordPress session) ------------- */

	private function qb_guard() {
		if ( ! $this->qb_token_ok() || ! $this->qb_cookie_ok() ) {
			wp_send_json_error( array( 'message' => __( 'Session expired — reopen the link.', 'mwm-studio' ) ), 403 );
		}
	}

	public function mwm_qb_slots() {
		$this->qb_guard();
		$date = isset( $_POST['date'] ) ? sanitize_text_field( wp_unslash( $_POST['date'] ) ) : '';
		$dur  = isset( $_POST['duration'] ) ? (float) $_POST['duration'] : 1;
		if ( ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', $date ) ) {
			wp_send_json_error( array( 'message' => 'bad date' ) );
		}
		$slots = $this->get_available_slots( $date, $dur );
		wp_send_json_success( array(
			'slots'   => ( null === $slots ) ? array() : array_values( $slots ),
			'unknown' => ( null === $slots ),
		) );
	}

	public function mwm_qb_create() {
		$this->qb_guard();
		$client_id = isset( $_POST['client_id'] ) ? (int) $_POST['client_id'] : 0;
		$res = $this->admin_write_booking(
			0,
			array(
				'client_id'      => $client_id,
				'booking_date'   => isset( $_POST['date'] ) ? sanitize_text_field( wp_unslash( $_POST['date'] ) ) : '',
				'start_time'     => isset( $_POST['start_time'] ) ? sanitize_text_field( wp_unslash( $_POST['start_time'] ) ) : '',
				'duration_hours' => isset( $_POST['duration'] ) ? (float) $_POST['duration'] : 0,
				'status'         => 'confirmed',
				'notes'          => 'Booked from the phone (quick book)',
			),
			array(
				'action'        => 'booking.quickbook',
				'reason'        => 'Quick Book — client asked Michael to book it',
				'notify_client' => ! empty( $_POST['notify'] ),
				'actor'         => 'quick-book (phone)',
			)
		);

		if ( ! $res['ok'] ) {
			wp_send_json_error( array( 'message' => $res['message'] ) );
		}

		$c    = $this->get_client( $client_id );
		$used = $c ? $this->hours_used_in_contract( $c->id, $c->contract_start_date, $c->contract_end_date ) : 0;
		$msg  = sprintf(
			/* translators: 1: client, 2: date, 3: time */
			__( 'Booked — <strong>%1$s</strong><br>%2$s at %3$s', 'mwm-studio' ),
			esc_html( $c ? $c->name : '' ),
			esc_html( date_i18n( 'l, F j', strtotime( sanitize_text_field( wp_unslash( $_POST['date'] ) ) ) ) ),
			esc_html( sanitize_text_field( wp_unslash( $_POST['start_time'] ) ) )
		);
		if ( $c ) {
			$msg .= '<br><small style="color:#6b7280">' . esc_html( sprintf( __( '%1$s of %2$s hours used', 'mwm-studio' ), number_format( $used, 2 ), number_format( (float) $c->contract_hours, 2 ) ) ) . '</small>';
		}
		foreach ( $res['warnings'] as $w ) {
			$msg .= '<br><small style="color:#c62828">' . esc_html( $w ) . '</small>';
		}
		wp_send_json_success( array( 'message' => $msg ) );
	}

	/* =========================================================================
	 * S27 — DRIFT WATCH
	 *
	 * The Reconciliation screen only tells you the truth on the day you think to
	 * open it. #61 drifted on Aug 12 and was found on Aug 13, by the client's
	 * time being wrong. This runs the same check every morning and speaks up
	 * only when something disagrees. Silence means clean.
	 * ========================================================================= */

	/** S27: shared by the Reconciliation screen and the daily cron. */
	private function find_calendar_drift( $from, $to ) {
		global $wpdb;
		$rows = $wpdb->get_results(
			$wpdb->prepare(
				"SELECT b.*, c.name AS client_name FROM {$this->bookings_table} b
				LEFT JOIN {$this->clients_table} c ON c.id = b.client_id
				WHERE b.status IN ('confirmed','completed')
				AND b.booking_date >= %s AND b.booking_date <= %s
				ORDER BY b.booking_date ASC, b.start_time ASC",
				$from,
				$to
			)
		);

		$checked = 0;
		$unknown = 0;
		$bad     = array();
		foreach ( $rows as $r ) {
			$blocks = $this->get_gcal_busy_blocks( $r->booking_date );
			if ( null === $blocks ) {
				$unknown++;
				continue;
			}
			$checked++;
			$s     = substr( $r->start_time, 0, 5 );
			$e     = substr( $r->end_time, 0, 5 );
			$match = false;
			$near  = array();
			foreach ( $blocks as $bl ) {
				if ( $bl['start'] === $s && $bl['end'] === $e ) {
					$match = true;
					break;
				}
				if ( $bl['start'] < $e && $bl['end'] > $s ) {
					$near[] = $bl['start'] . '–' . $bl['end'];
				}
			}
			if ( ! $match ) {
				$bad[] = array( 'b' => $r, 'near' => $near );
			}
		}
		return array( 'checked' => $checked, 'unknown' => $unknown, 'bad' => $bad );
	}

	public function ensure_drift_cron() {
		if ( ! wp_next_scheduled( 'mwm_studio_drift_event' ) ) {
			// ~7:10am local, daily.
			$first = strtotime( 'tomorrow 07:10', current_time( 'timestamp' ) ) - ( (int) get_option( 'gmt_offset' ) * HOUR_IN_SECONDS );
			wp_schedule_event( $first, 'daily', 'mwm_studio_drift_event' );
		}
	}

	public function run_drift_check() {
		$from = date( 'Y-m-d', strtotime( current_time( 'Y-m-d' ) . ' -7 days' ) );
		$to   = date( 'Y-m-d', strtotime( current_time( 'Y-m-d' ) . ' +60 days' ) );
		$r    = $this->find_calendar_drift( $from, $to );

		if ( empty( $r['bad'] ) ) {
			update_option( 'mwm_studio_drift_last', array( 'at' => current_time( 'mysql' ), 'checked' => $r['checked'], 'bad' => 0 ), false );
			return; // silence means clean
		}

		$lines = array();
		foreach ( $r['bad'] as $x ) {
			$b       = $x['b'];
			$lines[] = sprintf(
				"#%d  %s — booking says %s %s–%s · calendar has %s",
				(int) $b->id,
				$b->client_name ? $b->client_name : ( $b->guest_name . ' (rental)' ),
				$b->booking_date,
				substr( $b->start_time, 0, 5 ),
				substr( $b->end_time, 0, 5 ),
				$x['near'] ? implode( ', ', $x['near'] ) : 'nothing at all'
			);
		}
		$body = sprintf(
			"%d booking(s) no longer match their Google Calendar event.\n\n%s\n\nThe BOOKING ROW is the source of truth — reminder emails read it, not the calendar.\nOpen each one and re-save it to rewrite the calendar event to match:\n%s\n\n%d checked%s.\n",
			count( $r['bad'] ),
			implode( "\n", $lines ),
			admin_url( 'admin.php?page=mwm-studio-reconcile' ),
			$r['checked'],
			$r['unknown'] ? sprintf( ', %d could not be checked (availability feed unreachable)', $r['unknown'] ) : ''
		);

		$this->notify_admin( sprintf( '[MWM Studio] ⚠️ %d booking(s) drifted from the calendar', count( $r['bad'] ) ), $body );

		// Optional Slack relay — paste an incoming-webhook URL in Settings to use it.
		$hook = trim( (string) get_option( 'mwm_studio_drift_slack', '' ) );
		if ( $hook ) {
			wp_remote_post( $hook, array(
				'timeout' => 5,
				'headers' => array( 'Content-Type' => 'application/json' ),
				'body'    => wp_json_encode( array(
					'text' => "⚠️ *Studio booking drifted from the calendar*\n```" . implode( "\n", $lines ) . '```',
				) ),
			) );
		}

		update_option( 'mwm_studio_drift_last', array( 'at' => current_time( 'mysql' ), 'checked' => $r['checked'], 'bad' => count( $r['bad'] ) ), false );
	}

	public function render_dashboard_page() {
		global $wpdb;
		$total_clients = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$this->clients_table} WHERE active = 1" );

		$month = (int) current_time( 'n' );
		$year  = (int) current_time( 'Y' );

		$bookings_this_month = (int) $wpdb->get_var(
			$wpdb->prepare(
				"SELECT COUNT(*) FROM {$this->bookings_table} WHERE status IN ('confirmed','completed','cancelled_late') AND YEAR(booking_date)=%d AND MONTH(booking_date)=%d",
				$year,
				$month
			)
		);

		$hours_booked = (float) $wpdb->get_var(
			$wpdb->prepare(
				"SELECT COALESCE(SUM(duration_hours),0) FROM {$this->bookings_table} WHERE status IN ('confirmed','completed','cancelled_late') AND YEAR(booking_date)=%d AND MONTH(booking_date)=%d",
				$year,
				$month
			)
		);

		$hours_available = (float) $wpdb->get_var( "SELECT COALESCE(SUM(contract_hours),0) FROM {$this->clients_table} WHERE active = 1" );

		$upcoming = $wpdb->get_results(
			$wpdb->prepare(
				"SELECT b.*, c.name AS client_name FROM {$this->bookings_table} b
				LEFT JOIN {$this->clients_table} c ON c.id = b.client_id
				WHERE b.status = 'confirmed' AND TIMESTAMP(b.booking_date,b.start_time) >= %s
				ORDER BY b.booking_date ASC, b.start_time ASC LIMIT 10",
				current_time( 'mysql' )
			)
		);
		?>
		<div class="wrap mwm-studio-admin">
			<h1><?php esc_html_e( 'Studio Bookings Dashboard', 'mwm-studio' ); ?></h1>
			<div class="mwm-stat-cards">
				<div class="mwm-stat-card">
					<span class="mwm-stat-num"><?php echo esc_html( $total_clients ); ?></span>
					<span class="mwm-stat-label"><?php esc_html_e( 'Active Clients', 'mwm-studio' ); ?></span>
				</div>
				<div class="mwm-stat-card">
					<span class="mwm-stat-num"><?php echo esc_html( $bookings_this_month ); ?></span>
					<span class="mwm-stat-label"><?php esc_html_e( 'Bookings This Month', 'mwm-studio' ); ?></span>
				</div>
				<div class="mwm-stat-card">
					<span class="mwm-stat-num"><?php echo esc_html( number_format( $hours_booked, 1 ) ); ?></span>
					<span class="mwm-stat-label"><?php esc_html_e( 'Hours Booked This Month', 'mwm-studio' ); ?></span>
				</div>
				<div class="mwm-stat-card">
					<span class="mwm-stat-num"><?php echo esc_html( number_format( $hours_available, 1 ) ); ?></span>
					<span class="mwm-stat-label"><?php esc_html_e( 'Total Contract Hours Available', 'mwm-studio' ); ?></span>
				</div>
			</div>

			<h2><?php esc_html_e( 'Upcoming Bookings', 'mwm-studio' ); ?></h2>
			<table class="widefat striped">
				<thead>
					<tr>
						<th><?php esc_html_e( 'Client', 'mwm-studio' ); ?></th>
						<th><?php esc_html_e( 'Date', 'mwm-studio' ); ?></th>
						<th><?php esc_html_e( 'Time', 'mwm-studio' ); ?></th>
						<th><?php esc_html_e( 'Duration', 'mwm-studio' ); ?></th>
					</tr>
				</thead>
				<tbody>
				<?php if ( $upcoming ) : ?>
					<?php foreach ( $upcoming as $b ) : ?>
						<tr>
							<td><?php echo esc_html( $b->client_name ? $b->client_name : ( $b->guest_name ? $b->guest_name . ' (rental)' : '—' ) ); ?></td>
							<td><?php echo esc_html( date_i18n( 'M j, Y', strtotime( $b->booking_date ) ) ); ?></td>
							<td><?php echo esc_html( substr( $b->start_time, 0, 5 ) . ' - ' . substr( $b->end_time, 0, 5 ) ); ?></td>
							<td><?php echo esc_html( $b->duration_hours ); ?>h</td>
						</tr>
					<?php endforeach; ?>
				<?php else : ?>
					<tr><td colspan="4"><?php esc_html_e( 'No upcoming bookings.', 'mwm-studio' ); ?></td></tr>
				<?php endif; ?>
				</tbody>
			</table>

			<p style="margin-top:20px;">
				<?php esc_html_e( 'Shortcode for the client portal:', 'mwm-studio' ); ?>
				<code>[mwm_studio_portal]</code>
			</p>
		</div>
		<?php
		$this->print_admin_css();
	}

	/* =========================================================================
	 * ADMIN PAGE: CLIENTS
	 * ========================================================================= */

	public function render_clients_page() {
		global $wpdb;

		if ( isset( $_GET['deleted'] ) ) {
			echo '<div class="notice notice-success is-dismissible"><p>' . esc_html__( 'Client deleted.', 'mwm-studio' ) . '</p></div>';
		}
		if ( $err = get_transient( 'mwm_studio_admin_error' ) ) {
			delete_transient( 'mwm_studio_admin_error' );
			echo '<div class="notice notice-error is-dismissible"><p>' . esc_html( $err ) . '</p></div>';
		}

		$this->print_admin_notice(); // S26

		$edit_id = isset( $_GET['edit'] ) ? (int) $_GET['edit'] : 0;
		$editing = null;
		if ( $edit_id ) {
			$editing = $this->get_client( $edit_id );
		}

		foreach ( array( 'created', 'updated', 'regenerated' ) as $flag ) {
			if ( isset( $_GET[ $flag ] ) ) {
				$cid  = (int) $_GET[ $flag ];
				$code = get_transient( 'mwm_studio_new_code_' . $cid );
				if ( $code ) {
					echo '<div class="notice notice-success"><p>' . esc_html__( 'Access code:', 'mwm-studio' ) . ' <code style="font-size:16px;">' . esc_html( $code ) . '</code> — ' . esc_html__( 'save this now, it will not be shown again.', 'mwm-studio' ) . '</p></div>';
					delete_transient( 'mwm_studio_new_code_' . $cid );
				} else {
					echo '<div class="notice notice-success is-dismissible"><p>' . esc_html__( 'Client saved.', 'mwm-studio' ) . '</p></div>';
				}
			}
		}

		$clients = $wpdb->get_results( "SELECT * FROM {$this->clients_table} ORDER BY name ASC" );
		$month   = (int) current_time( 'n' );
		$year    = (int) current_time( 'Y' );
		?>
		<div class="wrap mwm-studio-admin">
			<h1><?php esc_html_e( 'Studio Clients', 'mwm-studio' ); ?></h1>

			<div class="mwm-admin-columns">
				<div class="mwm-admin-form-col">
					<div class="mwm-card">
						<h2><?php echo $editing ? esc_html__( 'Edit Client', 'mwm-studio' ) : esc_html__( 'Add New Client', 'mwm-studio' ); ?></h2>
						<form method="post">
							<?php wp_nonce_field( 'mwm_studio_save_client' ); ?>
							<input type="hidden" name="mwm_studio_action" value="save_client" />
							<input type="hidden" name="client_id" value="<?php echo esc_attr( $editing ? $editing->id : 0 ); ?>" />

							<p><label><?php esc_html_e( 'Name', 'mwm-studio' ); ?></label>
							<input type="text" name="name" class="widefat" required value="<?php echo esc_attr( $editing ? $editing->name : '' ); ?>"></p>

							<p><label><?php esc_html_e( 'Email', 'mwm-studio' ); ?></label>
							<input type="email" name="email" class="widefat" required value="<?php echo esc_attr( $editing ? $editing->email : '' ); ?>"></p>

							<p><label><?php esc_html_e( 'Phone', 'mwm-studio' ); ?></label>
							<input type="text" name="phone" class="widefat" value="<?php echo esc_attr( $editing ? $editing->phone : '' ); ?>"></p>

							<p><label><?php esc_html_e( 'Company', 'mwm-studio' ); ?></label>
							<input type="text" name="company" class="widefat" value="<?php echo esc_attr( $editing ? $editing->company : '' ); ?>"></p>

							<p><label><?php esc_html_e( 'Package Name', 'mwm-studio' ); ?></label>
							<input type="text" name="package_name" class="widefat" placeholder="e.g. Podcast Pro" value="<?php echo esc_attr( $editing ? $editing->package_name : '' ); ?>"></p>

							<p><label><?php esc_html_e( 'Contract Hours (total)', 'mwm-studio' ); ?></label>
							<input type="number" step="0.5" min="0" name="contract_hours" class="widefat" value="<?php echo esc_attr( $editing ? $editing->contract_hours : '12.0' ); ?>"></p>

							<p><label><?php esc_html_e( 'Contract Start Date', 'mwm-studio' ); ?></label>
							<input type="date" name="contract_start_date" class="widefat" value="<?php echo esc_attr( $editing && $editing->contract_start_date ? $editing->contract_start_date : '' ); ?>">
							<small style="color:#666;"><?php esc_html_e( 'First payment date. End date auto-calculates to 3 months later.', 'mwm-studio' ); ?></small></p>

							<p><label><?php esc_html_e( 'Contract End Date', 'mwm-studio' ); ?></label>
							<input type="date" name="contract_end_date" class="widefat" value="<?php echo esc_attr( $editing && $editing->contract_end_date ? $editing->contract_end_date : '' ); ?>">
							<small style="color:#666;"><?php esc_html_e( 'Leave blank to auto-calculate (start + 3 months).', 'mwm-studio' ); ?></small></p>

							<input type="hidden" name="monthly_hours" value="<?php echo esc_attr( $editing ? $editing->monthly_hours : '4.0' ); ?>" />

							<p>
								<label><?php esc_html_e( 'Access Code', 'mwm-studio' ); ?></label>
								<span style="display:flex;gap:8px;">
									<input type="text" name="access_code" id="mwm-access-code" maxlength="6" class="widefat" placeholder="<?php echo $editing ? esc_attr__( 'Leave blank to keep current code', 'mwm-studio' ) : esc_attr__( 'Auto-generate or type your own', 'mwm-studio' ); ?>">
									<button type="button" class="button" onclick="document.getElementById('mwm-access-code').value = mwmGenCode();"><?php esc_html_e( 'Generate', 'mwm-studio' ); ?></button>
								</span>
							</p>

							<p><label><input type="checkbox" name="active" <?php checked( $editing ? (bool) $editing->active : true ); ?> /> <?php esc_html_e( 'Active', 'mwm-studio' ); ?></label></p>

							<p><label><?php esc_html_e( 'Notes', 'mwm-studio' ); ?></label>
							<textarea name="notes" class="widefat" rows="3"><?php echo esc_textarea( $editing ? $editing->notes : '' ); ?></textarea></p>

							<p>
								<button type="submit" class="button button-primary"><?php echo $editing ? esc_html__( 'Update Client', 'mwm-studio' ) : esc_html__( 'Add Client', 'mwm-studio' ); ?></button>
								<?php if ( $editing ) : ?>
									<a href="<?php echo esc_url( admin_url( 'admin.php?page=mwm-studio-clients' ) ); ?>" class="button"><?php esc_html_e( 'Cancel', 'mwm-studio' ); ?></a>
								<?php endif; ?>
							</p>
						</form>
					</div>
				</div>

				<div class="mwm-admin-table-col">
					<table class="widefat striped">
						<thead>
							<tr>
								<th><?php esc_html_e( 'Name', 'mwm-studio' ); ?></th>
								<th><?php esc_html_e( 'Email', 'mwm-studio' ); ?></th>
								<th><?php esc_html_e( 'Package', 'mwm-studio' ); ?></th>
								<th><?php esc_html_e( 'Contract Hours Used / Total', 'mwm-studio' ); ?></th>
								<th><?php esc_html_e( 'Status', 'mwm-studio' ); ?></th>
								<th><?php esc_html_e( 'Actions', 'mwm-studio' ); ?></th>
							</tr>
						</thead>
						<tbody>
						<?php if ( $clients ) : ?>
							<?php foreach ( $clients as $c ) : ?>
								<?php $used = $this->hours_used_in_contract( $c->id, $c->contract_start_date, $c->contract_end_date ); ?>
								<tr>
									<td><strong><?php echo esc_html( $c->name ); ?></strong></td>
									<td><?php echo esc_html( $c->email ); ?></td>
									<td><?php echo esc_html( $c->package_name ); ?></td>
									<td>
									<?php echo esc_html( number_format( $used, 1 ) . ' / ' . number_format( $c->contract_hours, 1 ) ); ?>
									<?php if ( $c->contract_end_date ) : ?>
										<br><small style="color:#666;"><?php echo esc_html( date_i18n( 'M j', strtotime( $c->contract_start_date ) ) . ' – ' . date_i18n( 'M j, Y', strtotime( $c->contract_end_date ) ) ); ?></small>
										<?php if ( current_time( 'Y-m-d' ) > $c->contract_end_date ) : ?>
											<br><small style="color:#c62828;font-weight:600;"><?php esc_html_e( 'EXPIRED', 'mwm-studio' ); ?></small>
										<?php endif; ?>
									<?php endif; ?>
									<?php if ( $used > (float) $c->contract_hours + 0.001 ) : ?>
										<br><small style="color:#c62828;font-weight:600;"><?php echo esc_html( sprintf( __( 'OVER by %s h', 'mwm-studio' ), number_format( $used - (float) $c->contract_hours, 2 ) ) ); ?></small>
									<?php endif; ?>
									<?php // S26: adjust the package without editing the database by hand. ?>
									<form method="post" style="margin-top:6px;display:flex;gap:4px;align-items:center;">
										<?php wp_nonce_field( 'mwm_studio_adjust_hours' ); ?>
										<input type="hidden" name="mwm_studio_action" value="adjust_hours" />
										<input type="hidden" name="client_id" value="<?php echo esc_attr( $c->id ); ?>" />
										<select name="hours_mode" style="font-size:11px;height:26px;padding:0 4px;">
											<option value="add"><?php esc_html_e( 'Add', 'mwm-studio' ); ?></option>
											<option value="set"><?php esc_html_e( 'Set total', 'mwm-studio' ); ?></option>
										</select>
										<input type="number" name="hours_value" step="0.25" style="width:70px;height:26px;" placeholder="0.5" required />
										<button class="button button-small"><?php esc_html_e( 'Apply', 'mwm-studio' ); ?></button>
									</form>
								</td>
									<td><?php echo $c->active ? '<span style="color:#2e7d32;">' . esc_html__( 'Active', 'mwm-studio' ) . '</span>' : '<span style="color:#c62828;">' . esc_html__( 'Inactive', 'mwm-studio' ) . '</span>'; ?></td>
									<td>
										<a href="<?php echo esc_url( admin_url( 'admin.php?page=mwm-studio-clients&edit=' . $c->id ) ); ?>"><?php esc_html_e( 'Edit', 'mwm-studio' ); ?></a>
										|
										<a href="<?php echo esc_url( admin_url( 'admin.php?page=mwm-studio-booking-edit&client_id=' . $c->id ) ); ?>"><?php esc_html_e( 'New Booking', 'mwm-studio' ); ?></a>
										|
										<a href="<?php echo esc_url( wp_nonce_url( admin_url( 'admin.php?page=mwm-studio-clients&mwm_action=regenerate_code&id=' . $c->id ), 'mwm_studio_regen_' . $c->id ) ); ?>" onclick="return confirm('<?php echo esc_js( __( 'Generate a new access code? The old one will stop working.', 'mwm-studio' ) ); ?>');"><?php esc_html_e( 'New Code', 'mwm-studio' ); ?></a>
										|
										<a href="<?php echo esc_url( wp_nonce_url( admin_url( 'admin.php?page=mwm-studio-clients&mwm_action=delete_client&id=' . $c->id ), 'mwm_studio_delete_client_' . $c->id ) ); ?>" onclick="return confirm('<?php echo esc_js( __( 'Delete this client? This cannot be undone.', 'mwm-studio' ) ); ?>');" style="color:#c62828;"><?php esc_html_e( 'Delete', 'mwm-studio' ); ?></a>
									</td>
								</tr>
							<?php endforeach; ?>
						<?php else : ?>
							<tr><td colspan="6"><?php esc_html_e( 'No clients yet.', 'mwm-studio' ); ?></td></tr>
						<?php endif; ?>
						</tbody>
					</table>
				</div>
			</div>
		</div>
		<script>
		function mwmGenCode(){
			var chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
			var code = '';
			for (var i=0;i<6;i++){ code += chars.charAt(Math.floor(Math.random()*chars.length)); }
			return code;
		}
		</script>
		<?php
		$this->print_admin_css();
	}

	/* =========================================================================
	 * ADMIN PAGE: BOOKINGS
	 * ========================================================================= */

	public function render_bookings_page() {
		global $wpdb;

		if ( isset( $_GET['cancelled'] ) ) {
			echo '<div class="notice notice-success is-dismissible"><p>' . esc_html__( 'Booking cancelled.', 'mwm-studio' ) . '</p></div>';
		}
		if ( isset( $_GET['completed'] ) ) {
			echo '<div class="notice notice-success is-dismissible"><p>' . esc_html__( 'Booking marked completed.', 'mwm-studio' ) . '</p></div>';
		}
		$this->print_admin_notice(); // S26

		$filter_client = isset( $_GET['client_id'] ) ? (int) $_GET['client_id'] : 0;
		$filter_status = isset( $_GET['status'] ) ? sanitize_text_field( wp_unslash( $_GET['status'] ) ) : '';
		$filter_from   = isset( $_GET['date_from'] ) ? sanitize_text_field( wp_unslash( $_GET['date_from'] ) ) : '';
		$filter_to     = isset( $_GET['date_to'] ) ? sanitize_text_field( wp_unslash( $_GET['date_to'] ) ) : '';

		$where  = array( '1=1' );
		$params = array();

		if ( $filter_client ) {
			$where[]  = 'b.client_id = %d';
			$params[] = $filter_client;
		}
		if ( $filter_status && in_array( $filter_status, array( 'confirmed', 'cancelled', 'completed', 'cancelled_late' ), true ) ) {
			$where[]  = 'b.status = %s';
			$params[] = $filter_status;
		}
		if ( $filter_from ) {
			$where[]  = 'b.booking_date >= %s';
			$params[] = $filter_from;
		}
		if ( $filter_to ) {
			$where[]  = 'b.booking_date <= %s';
			$params[] = $filter_to;
		}

		// S26: LEFT JOIN — an inner JOIN hid every rental (client_id = 0) from this
		// screen, so paid rentals existed on the calendar and nowhere in wp-admin.
		$sql = "SELECT b.*, c.name AS client_name FROM {$this->bookings_table} b
				LEFT JOIN {$this->clients_table} c ON c.id = b.client_id
				WHERE " . implode( ' AND ', $where ) . '
				ORDER BY b.booking_date DESC, b.start_time DESC LIMIT 200';

		$bookings = $params ? $wpdb->get_results( $wpdb->prepare( $sql, $params ) ) : $wpdb->get_results( $sql );

		$clients = $wpdb->get_results( "SELECT id, name FROM {$this->clients_table} ORDER BY name ASC" );
		?>
		<div class="wrap mwm-studio-admin">
			<h1 class="wp-heading-inline"><?php esc_html_e( 'Studio Bookings', 'mwm-studio' ); ?></h1>
			<a href="<?php echo esc_url( admin_url( 'admin.php?page=mwm-studio-booking-edit' ) ); ?>" class="page-title-action"><?php esc_html_e( 'Add Booking', 'mwm-studio' ); ?></a>
			<a href="<?php echo esc_url( admin_url( 'admin.php?page=mwm-studio-reconcile' ) ); ?>" class="page-title-action"><?php esc_html_e( 'Check against calendar', 'mwm-studio' ); ?></a>
			<hr class="wp-header-end" />

			<form method="get" class="mwm-filters">
				<input type="hidden" name="page" value="mwm-studio-bookings" />
				<select name="client_id">
					<option value=""><?php esc_html_e( 'All Clients', 'mwm-studio' ); ?></option>
					<?php foreach ( $clients as $c ) : ?>
						<option value="<?php echo esc_attr( $c->id ); ?>" <?php selected( $filter_client, $c->id ); ?>><?php echo esc_html( $c->name ); ?></option>
					<?php endforeach; ?>
				</select>
				<select name="status">
					<option value=""><?php esc_html_e( 'All Statuses', 'mwm-studio' ); ?></option>
					<option value="confirmed" <?php selected( $filter_status, 'confirmed' ); ?>><?php esc_html_e( 'Confirmed', 'mwm-studio' ); ?></option>
					<option value="completed" <?php selected( $filter_status, 'completed' ); ?>><?php esc_html_e( 'Completed', 'mwm-studio' ); ?></option>
					<option value="cancelled" <?php selected( $filter_status, 'cancelled' ); ?>><?php esc_html_e( 'Cancelled', 'mwm-studio' ); ?></option>
				</select>
				<input type="date" name="date_from" value="<?php echo esc_attr( $filter_from ); ?>" />
				<input type="date" name="date_to" value="<?php echo esc_attr( $filter_to ); ?>" />
				<button class="button"><?php esc_html_e( 'Filter', 'mwm-studio' ); ?></button>
				<a class="button" href="<?php echo esc_url( admin_url( 'admin.php?page=mwm-studio-bookings' ) ); ?>"><?php esc_html_e( 'Reset', 'mwm-studio' ); ?></a>
			</form>

			<table class="widefat striped">
				<thead>
					<tr>
						<th><?php esc_html_e( 'Client', 'mwm-studio' ); ?></th>
						<th><?php esc_html_e( 'Date', 'mwm-studio' ); ?></th>
						<th><?php esc_html_e( 'Time', 'mwm-studio' ); ?></th>
						<th><?php esc_html_e( 'Duration', 'mwm-studio' ); ?></th>
						<th><?php esc_html_e( 'Status', 'mwm-studio' ); ?></th>
						<th><?php esc_html_e( 'Actions', 'mwm-studio' ); ?></th>
					</tr>
				</thead>
				<tbody>
				<?php if ( $bookings ) : ?>
					<?php foreach ( $bookings as $b ) : ?>
						<tr>
							<td><?php echo esc_html( $b->client_name ? $b->client_name : ( $b->guest_name ? $b->guest_name . ' (rental)' : '—' ) ); ?></td>
							<td><?php echo esc_html( date_i18n( 'M j, Y', strtotime( $b->booking_date ) ) ); ?></td>
							<td><?php echo esc_html( substr( $b->start_time, 0, 5 ) . ' - ' . substr( $b->end_time, 0, 5 ) ); ?></td>
							<td><?php echo esc_html( $b->duration_hours ); ?>h</td>
							<td>
								<?php
								$colors = array( 'confirmed' => '#2e7d32', 'cancelled' => '#c62828', 'cancelled_late' => '#c62828', 'completed' => '#666' );
								$color  = isset( $colors[ $b->status ] ) ? $colors[ $b->status ] : '#333';
								?>
								<span style="color:<?php echo esc_attr( $color ); ?>;font-weight:600;text-transform:capitalize;"><?php echo esc_html( $b->status ); ?></span>
							</td>
							<td>
								<?php // S26: Edit is available on every status — "he ran 30 minutes over" is always discovered after the fact. ?>
								<a href="<?php echo esc_url( admin_url( 'admin.php?page=mwm-studio-booking-edit&id=' . $b->id ) ); ?>"><strong><?php esc_html_e( 'Edit', 'mwm-studio' ); ?></strong></a>
								<?php if ( 'confirmed' === $b->status ) : ?>
									|
									<a href="<?php echo esc_url( wp_nonce_url( admin_url( 'admin.php?page=mwm-studio-bookings&mwm_action=complete_booking&id=' . $b->id ), 'mwm_studio_complete_booking_' . $b->id ) ); ?>"><?php esc_html_e( 'Mark Completed', 'mwm-studio' ); ?></a>
									|
									<a href="<?php echo esc_url( wp_nonce_url( admin_url( 'admin.php?page=mwm-studio-bookings&mwm_action=cancel_booking&id=' . $b->id ), 'mwm_studio_cancel_booking_' . $b->id ) ); ?>" onclick="return confirm('<?php echo esc_js( __( 'Cancel this booking? The calendar event will be removed too.', 'mwm-studio' ) ); ?>');" style="color:#c62828;"><?php esc_html_e( 'Cancel', 'mwm-studio' ); ?></a>
								<?php endif; ?>
							</td>
						</tr>
					<?php endforeach; ?>
				<?php else : ?>
					<tr><td colspan="6"><?php esc_html_e( 'No bookings found.', 'mwm-studio' ); ?></td></tr>
				<?php endif; ?>
				</tbody>
			</table>
		</div>
		<?php
		$this->print_admin_css();
	}

	/* =========================================================================
	 * ADMIN PAGE: SETTINGS
	 * ========================================================================= */

	public function render_settings_page() {
		if ( isset( $_GET['saved'] ) ) {
			echo '<div class="notice notice-success is-dismissible"><p>' . esc_html__( 'Settings saved.', 'mwm-studio' ) . '</p></div>';
		}
		$settings = $this->get_settings();
		$days     = array(
			'monday'    => __( 'Monday', 'mwm-studio' ),
			'tuesday'   => __( 'Tuesday', 'mwm-studio' ),
			'wednesday' => __( 'Wednesday', 'mwm-studio' ),
			'thursday'  => __( 'Thursday', 'mwm-studio' ),
			'friday'    => __( 'Friday', 'mwm-studio' ),
			'saturday'  => __( 'Saturday', 'mwm-studio' ),
			'sunday'    => __( 'Sunday', 'mwm-studio' ),
		);
		?>
		<div class="wrap mwm-studio-admin">
			<h1><?php esc_html_e( 'Studio Booking Settings', 'mwm-studio' ); ?></h1>
			<form method="post">
				<?php wp_nonce_field( 'mwm_studio_save_settings' ); ?>
				<input type="hidden" name="mwm_studio_action" value="save_settings" />

				<div class="mwm-card">
					<h2><?php esc_html_e( 'Studio Info', 'mwm-studio' ); ?></h2>
					<table class="form-table">
						<tr>
							<th><label for="studio_name"><?php esc_html_e( 'Studio Name', 'mwm-studio' ); ?></label></th>
							<td><input type="text" id="studio_name" name="studio_name" class="regular-text" value="<?php echo esc_attr( $settings['studio_name'] ); ?>"></td>
						</tr>
						<tr>
							<th><label for="studio_address"><?php esc_html_e( 'Studio Address', 'mwm-studio' ); ?></label></th>
							<td><input type="text" id="studio_address" name="studio_address" class="regular-text" value="<?php echo esc_attr( $settings['studio_address'] ); ?>"></td>
						</tr>
					</table>
				</div>

				<div class="mwm-card">
					<h2><?php esc_html_e( 'Booking Rules', 'mwm-studio' ); ?></h2>
					<table class="form-table">
						<tr>
							<th><label for="min_booking_hours"><?php esc_html_e( 'Minimum Booking Duration (hours)', 'mwm-studio' ); ?></label></th>
							<td><input type="number" step="0.5" min="0.5" id="min_booking_hours" name="min_booking_hours" value="<?php echo esc_attr( $settings['min_booking_hours'] ); ?>"></td>
						</tr>
						<tr>
							<th><label for="max_advance_days"><?php esc_html_e( 'Maximum Advance Booking (days)', 'mwm-studio' ); ?></label></th>
							<td><input type="number" min="1" id="max_advance_days" name="max_advance_days" value="<?php echo esc_attr( $settings['max_advance_days'] ); ?>"></td>
						</tr>
						<tr>
							<th><label for="cancellation_hours"><?php esc_html_e( 'Cancellation Cutoff (hours before)', 'mwm-studio' ); ?></label></th>
							<td><input type="number" min="0" id="cancellation_hours" name="cancellation_hours" value="<?php echo esc_attr( $settings['cancellation_hours'] ); ?>"></td>
						</tr>
						<tr>
							<th><label for="buffer_minutes"><?php esc_html_e( 'Buffer Between Bookings (minutes)', 'mwm-studio' ); ?></label></th>
							<td><input type="number" min="0" step="5" id="buffer_minutes" name="buffer_minutes" value="<?php echo esc_attr( $settings['buffer_minutes'] ); ?>"></td>
						</tr>
					</table>
				</div>

				<div class="mwm-card">
					<h2><?php esc_html_e( 'Operating Hours', 'mwm-studio' ); ?></h2>
					<table class="widefat">
						<thead>
							<tr>
								<th><?php esc_html_e( 'Day', 'mwm-studio' ); ?></th>
								<th><?php esc_html_e( 'Open', 'mwm-studio' ); ?></th>
								<th><?php esc_html_e( 'Close', 'mwm-studio' ); ?></th>
								<th><?php esc_html_e( 'Closed', 'mwm-studio' ); ?></th>
							</tr>
						</thead>
						<tbody>
						<?php foreach ( $days as $key => $label ) : ?>
							<?php $day_conf = $settings['hours'][ $key ]; ?>
							<tr>
								<td><?php echo esc_html( $label ); ?></td>
								<td><input type="time" name="open_<?php echo esc_attr( $key ); ?>" value="<?php echo esc_attr( $day_conf['open'] ); ?>"></td>
								<td><input type="time" name="close_<?php echo esc_attr( $key ); ?>" value="<?php echo esc_attr( $day_conf['close'] ); ?>"></td>
								<td><input type="checkbox" name="closed_<?php echo esc_attr( $key ); ?>" <?php checked( ! empty( $day_conf['closed'] ) ); ?>></td>
							</tr>
						<?php endforeach; ?>
						</tbody>
					</table>
				</div>

				<div class="mwm-card">
					<h2><?php esc_html_e( 'Stripe Auto-Onboarding', 'mwm-studio' ); ?></h2>
					<p style="color:#666;margin-top:0;"><?php esc_html_e( 'When a client pays through your Stripe checkout, they are automatically added to the portal and receive a welcome email with their access code.', 'mwm-studio' ); ?></p>
					<table class="form-table">
						<tr>
							<th><label for="stripe_webhook_secret"><?php esc_html_e( 'Webhook Signing Secret', 'mwm-studio' ); ?></label></th>
							<td>
								<input type="password" id="stripe_webhook_secret" name="stripe_webhook_secret" class="regular-text" value="<?php echo esc_attr( $settings['stripe_webhook_secret'] ); ?>" placeholder="whsec_...">
								<p class="description"><?php printf( esc_html__( 'Webhook URL: %s', 'mwm-studio' ), '<code>' . esc_html( rest_url( 'mwm-studio/v1/stripe-webhook' ) ) . '</code>' ); ?></p>
							</td>
						</tr>
						<tr>
							<th><label for="stripe_package_product_id"><?php esc_html_e( 'Stripe Product ID', 'mwm-studio' ); ?></label></th>
							<td><input type="text" id="stripe_package_product_id" name="stripe_package_product_id" class="regular-text" value="<?php echo esc_attr( $settings['stripe_package_product_id'] ); ?>" placeholder="prod_..."></td>
						</tr>
						<tr>
							<th><label for="stripe_contract_hours"><?php esc_html_e( 'Contract Hours', 'mwm-studio' ); ?></label></th>
							<td><input type="number" step="0.5" min="1" id="stripe_contract_hours" name="stripe_contract_hours" value="<?php echo esc_attr( $settings['stripe_contract_hours'] ); ?>"></td>
						</tr>
						<tr>
							<th><label for="stripe_contract_months"><?php esc_html_e( 'Contract Duration (months)', 'mwm-studio' ); ?></label></th>
							<td><input type="number" min="1" id="stripe_contract_months" name="stripe_contract_months" value="<?php echo esc_attr( $settings['stripe_contract_months'] ); ?>"></td>
						</tr>
					</table>
				</div>

				<div class="mwm-card">
					<h2><?php esc_html_e( 'Quick Book (phone)', 'mwm-studio' ); ?></h2>
					<p style="color:#666;margin-top:0;"><?php esc_html_e( 'Open this on your phone and add it to your home screen. It books for existing clients only — it cannot cancel, change hours or edit a client. Treat the link like a key.', 'mwm-studio' ); ?></p>
					<p><input type="text" class="widefat" readonly onclick="this.select();" value="<?php echo esc_attr( $this->qb_url() ); ?>" /></p>
					<p>
						<a class="button" href="<?php echo esc_url( wp_nonce_url( admin_url( 'admin.php?page=mwm-studio-settings&mwm_action=rotate_qb' ), 'mwm_studio_rotate_qb' ) ); ?>" onclick="return confirm('<?php echo esc_js( __( 'This kills the old link and clears the PIN. You will set a new PIN next time you open it. Continue?', 'mwm-studio' ) ); ?>');"><?php esc_html_e( 'New link + reset PIN', 'mwm-studio' ); ?></a>
						<span style="color:#666;margin-left:8px;"><?php echo esc_html( $this->qb_pin_hash() ? __( 'A PIN is set.', 'mwm-studio' ) : __( 'No PIN yet — the first person to open the link sets it.', 'mwm-studio' ) ); ?></span>
					</p>
					<h3 style="margin-bottom:4px;"><?php esc_html_e( 'Daily calendar drift alert', 'mwm-studio' ); ?></h3>
					<p style="color:#666;margin-top:0;"><?php esc_html_e( 'Every morning, every booking is checked against the calendar. You only hear about it when something disagrees. Emails you either way; paste a Slack incoming-webhook URL to also post there.', 'mwm-studio' ); ?></p>
					<p><input type="url" name="drift_slack" class="widefat" placeholder="https://hooks.slack.com/services/..." value="<?php echo esc_attr( get_option( 'mwm_studio_drift_slack', '' ) ); ?>" /></p>
					<?php $mwm_last = get_option( 'mwm_studio_drift_last' ); ?>
					<?php if ( is_array( $mwm_last ) ) : ?>
						<p style="color:#666;"><?php echo esc_html( sprintf( __( 'Last run %1$s — %2$d checked, %3$d disagreed.', 'mwm-studio' ), $mwm_last['at'], (int) $mwm_last['checked'], (int) $mwm_last['bad'] ) ); ?></p>
					<?php endif; ?>
				</div>

				<p><button type="submit" class="button button-primary button-hero"><?php esc_html_e( 'Save Settings', 'mwm-studio' ); ?></button></p>
			</form>
		</div>
		<?php
		$this->print_admin_css();
	}

	/* =========================================================================
	 * STRIPE WEBHOOK — AUTO-ONBOARDING
	 * ========================================================================= */

	/* =========================================================================
	 * S28 — GOOGLE CALENDAR -> PORTAL SYNC
	 *
	 * The booking row stays the only source of truth. The calendar becomes an
	 * INPUT DEVICE, not a second truth: a drag is Michael expressing an
	 * intention, and that intention is run through admin_write_booking() like
	 * every other change. What comes out the other side is the row.
	 *
	 * Because the change came FROM the calendar, the calendar is already in the
	 * target state — so these writes carry push_calendar => false. The event
	 * does not blink, keeps its id, and the client gets no cancellation notice
	 * and no fresh invite for a move Michael made with his thumb.
	 *
	 * POLICY (settled with Michael, Aug 13–14):
	 *   drag to a free slot ............ row follows, silent
	 *   drag onto another booking ...... accepted, flagged loudly
	 *   drag past the contract end ..... accepted, flagged
	 *   drag beyond remaining hours .... accepted, flagged, ledger goes negative
	 *   resize ......................... same as a move, hours follow
	 *   DELETE the event ............... asks first. Nothing is cancelled.
	 * Never silently refused: Michael is standing in a studio, not reading a
	 * validation error.
	 * ========================================================================= */

	public function register_calendar_sync_route() {
		register_rest_route( 'mwm-studio/v1', '/calendar-sync', array(
			'methods'             => 'POST',
			'callback'            => array( $this, 'handle_calendar_sync' ),
			'permission_callback' => '__return_true', // Shared secret checked inside, like the Stripe route.
		) );
	}

	/** S28: the machine and WordPress already share this secret in both directions. */
	private function cal_sync_authorized( $request ) {
		$secret = (string) get_option( 'mwm_portal_provision_secret', '' );
		$given  = (string) $request->get_header( 'x-mwm-portal-secret' );
		return ( '' !== $secret && '' !== $given && hash_equals( $secret, $given ) );
	}

	/** S28: what the machine stores as "the position we last agreed on". */
	private function cal_booking_snapshot( $b ) {
		return array(
			'date'     => $b->booking_date,
			'start'    => substr( $b->start_time, 0, 5 ),
			'end'      => substr( $b->end_time, 0, 5 ),
			'duration' => (float) $b->duration_hours,
			'status'   => (string) $b->status,
		);
	}

	public function handle_calendar_sync( \WP_REST_Request $request ) {
		if ( ! $this->cal_sync_authorized( $request ) ) {
			return new \WP_REST_Response( array( 'ok' => false, 'error' => 'unauthorized' ), 401 );
		}
		global $wpdb;

		$p = $request->get_json_params();
		if ( ! is_array( $p ) ) {
			$p = $request->get_params();
		}
		$booking_id = isset( $p['booking_id'] ) ? (int) $p['booking_id'] : 0;
		$event_id   = isset( $p['event_id'] ) ? sanitize_text_field( (string) $p['event_id'] ) : '';
		$action     = isset( $p['action'] ) ? sanitize_text_field( (string) $p['action'] ) : '';

		if ( ! $booking_id || ! in_array( $action, array( 'moved', 'deleted' ), true ) ) {
			return new \WP_REST_Response( array( 'ok' => false, 'error' => 'bad payload' ), 400 );
		}

		$b = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->bookings_table} WHERE id = %d", $booking_id ) );
		if ( ! $b ) {
			// Not an error worth retrying forever: the row is gone, the event is stray.
			return new \WP_REST_Response( array( 'ok' => true, 'state' => 'noop', 'booking_id' => $booking_id, 'reason' => 'booking not found' ), 200 );
		}
		$label = $this->booking_client_label( (int) $b->client_id, $b );

		if ( ! $this->status_holds_calendar( $b->status ) ) {
			return new \WP_REST_Response( array(
				'ok'         => true,
				'state'      => 'noop',
				'booking_id' => $booking_id,
				'client'     => $label,
				'reason'     => sprintf( 'booking is %s', $b->status ),
				'booking'    => $this->cal_booking_snapshot( $b ),
			), 200 );
		}

		if ( 'deleted' === $action ) {
			return $this->cal_sync_deleted( $b, $event_id, $label );
		}

		$date  = isset( $p['date'] ) ? sanitize_text_field( (string) $p['date'] ) : '';
		$start = isset( $p['start_time'] ) ? substr( sanitize_text_field( (string) $p['start_time'] ), 0, 5 ) : '';
		$end   = isset( $p['end_time'] ) ? substr( sanitize_text_field( (string) $p['end_time'] ), 0, 5 ) : '';
		if ( ! preg_match( '/^\d{4}-\d{2}-\d{2}$/', $date )
			|| ! preg_match( '/^([01]\d|2[0-3]):([0-5]\d)$/', $start )
			|| ! preg_match( '/^([01]\d|2[0-3]):([0-5]\d)$/', $end ) ) {
			return new \WP_REST_Response( array( 'ok' => false, 'error' => 'bad times' ), 400 );
		}

		/*
		 * Loop guard, layer 2 — and this is the copy that counts, because this is
		 * the code that owns the row. Every echo of our own write dies here
		 * without a database call, an audit entry, or an alert.
		 */
		if ( $b->booking_date === $date
			&& substr( $b->start_time, 0, 5 ) === $start
			&& substr( $b->end_time, 0, 5 ) === $end ) {
			return new \WP_REST_Response( array(
				'ok'         => true,
				'state'      => 'unchanged',
				'booking_id' => $booking_id,
				'client'     => $label,
				'booking'    => $this->cal_booking_snapshot( $b ),
			), 200 );
		}

		$duration = ( strtotime( $date . ' ' . $end . ':00' ) - strtotime( $date . ' ' . $start . ':00' ) ) / HOUR_IN_SECONDS;
		if ( $duration <= 0 ) {
			// An event dragged across midnight. The row cannot hold it, and
			// guessing which day Michael meant is how #61 happened.
			return new \WP_REST_Response( array(
				'ok'         => true,
				'state'      => 'refused',
				'booking_id' => $booking_id,
				'client'     => $label,
				'message'    => sprintf( 'The calendar event for booking #%d now runs past midnight (%s %s–%s). The booking was left where it was — move it in wp-admin instead.', $booking_id, $date, $start, $end ),
				'booking'    => $this->cal_booking_snapshot( $b ),
			), 200 );
		}

		$res = $this->admin_write_booking(
			$booking_id,
			array(
				'booking_date'   => $date,
				'start_time'     => $start,
				'duration_hours' => $duration,
			),
			array(
				'action'         => 'booking.calendar_drag',
				'reason'         => sprintf( 'Moved on Google Calendar (event %s)', $event_id ? $event_id : 'unknown' ),
				'actor'          => 'google-calendar',
				'push_calendar'  => false, // the calendar is already in the target state
				'allow_conflict' => true,  // accept and flag; never refuse a drag
				'notify_client'  => false,
			)
		);

		if ( empty( $res['ok'] ) ) {
			// ok => true on purpose. The machine treats a hard failure as "do not
			// advance the syncToken", which is right for an unreachable portal and
			// wrong for a write the portal has considered and declined: that would
			// re-fire and re-alert every two minutes forever. This is flagged once,
			// loudly, and the morning drift check keeps nagging until it is fixed.
			return new \WP_REST_Response( array(
				'ok'         => true,
				'state'      => 'refused',
				'booking_id' => $booking_id,
				'client'     => $label,
				'message'    => sprintf( 'Booking #%d could not follow the calendar to %s %s–%s: %s', $booking_id, $date, $start, $end, isset( $res['message'] ) ? $res['message'] : 'the write was refused' ),
				'booking'    => $this->cal_booking_snapshot( $b ),
			), 200 );
		}

		$after = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->bookings_table} WHERE id = %d", $booking_id ) );
		return new \WP_REST_Response( array(
			'ok'         => true,
			'state'      => 'updated',
			'booking_id' => $booking_id,
			'client'     => $label,
			'warnings'   => isset( $res['warnings'] ) ? array_values( $res['warnings'] ) : array(),
			'booking'    => $after ? $this->cal_booking_snapshot( $after ) : null,
		), 200 );
	}

	/**
	 * S28 · 4.1 — A DELETION IS A QUESTION, NOT A COMMAND.
	 *
	 * The client is only an attendee: deleting from their own calendar marks
	 * them declined and leaves ours untouched, and the sync ignores that. A real
	 * deletion means someone with write access to MWM CREATIONS removed it,
	 * which in practice means Michael on his phone. So the two realistic cases
	 * are "I meant to cancel this" and "I fat-fingered it".
	 *
	 * The event stays gone. Nothing is cancelled, no hours move, no email goes
	 * to the client. Two one-tap signed links go to Slack instead — the same
	 * HMAC pattern /manage-booking/ already uses, which works from his phone
	 * with no login and needs no Slack app change (the machine holds a bot
	 * token and can only post messages; interactive buttons would need an
	 * interactivity request URL configured).
	 *
	 * If he never answers, nothing happens: the booking stands and the daily
	 * drift check flags it every morning until it is resolved. That nag IS the
	 * fallback — no timeout logic, and no state expiring into a silent wrong
	 * answer.
	 */
	private function cal_sync_deleted( $b, $event_id, $label ) {
		$bid   = (int) $b->id;
		$nonce = wp_generate_password( 20, false, false );
		update_option(
			$this->cal_del_key( $bid ),
			array(
				'event_id' => $event_id,
				'nonce'    => $nonce,
				'asked_at' => current_time( 'mysql' ),
				'answered' => '',
			),
			false
		);

		$question = sprintf(
			"Booking #%d · %s · %s, %s–%s\nYou deleted the calendar event. Cancel the booking and return the %s hour(s)?",
			$bid,
			$label,
			date_i18n( 'D M j', strtotime( $b->booking_date ) ),
			substr( $b->start_time, 0, 5 ),
			substr( $b->end_time, 0, 5 ),
			rtrim( rtrim( number_format( (float) $b->duration_hours, 2 ), '0' ), '.' )
		);

		return new \WP_REST_Response( array(
			'ok'         => true,
			'state'      => 'ask',
			'booking_id' => $bid,
			'client'     => $label,
			'question'   => $question,
			'yes_url'    => $this->cal_answer_url( $bid, $nonce, 'yes' ),
			'no_url'     => $this->cal_answer_url( $bid, $nonce, 'no' ),
			'booking'    => $this->cal_booking_snapshot( $b ),
		), 200 );
	}

	private function cal_del_key( $bid ) {
		return 'mwm_studio_caldel_' . (int) $bid;
	}

	private function cal_answer_token( $bid, $nonce, $answer ) {
		return substr( hash_hmac( 'sha256', 'caldel|' . (int) $bid . '|' . $nonce . '|' . $answer, wp_salt( 'auth' ) ), 0, 32 );
	}

	private function cal_answer_url( $bid, $nonce, $answer ) {
		return add_query_arg(
			array(
				'mwm_cal_answer' => 1,
				'b'              => (int) $bid,
				'a'              => $answer,
				't'              => $this->cal_answer_token( $bid, $nonce, $answer ),
			),
			home_url( '/' )
		);
	}

	/**
	 * S28: Michael taps one of the two links. Single use — the answer is
	 * consumed BEFORE the write, so a stale link in Slack scrollback, a double
	 * tap, or a link-preview fetch cannot re-fire it.
	 */
	public function cal_answer_handler() {
		if ( ! isset( $_GET['mwm_cal_answer'] ) ) {
			return;
		}
		$bid = isset( $_GET['b'] ) ? (int) $_GET['b'] : 0;
		$ans = isset( $_GET['a'] ) ? sanitize_text_field( wp_unslash( $_GET['a'] ) ) : '';
		$tok = isset( $_GET['t'] ) ? sanitize_text_field( wp_unslash( $_GET['t'] ) ) : '';

		if ( ! $bid || ! in_array( $ans, array( 'yes', 'no' ), true ) || strlen( $tok ) < 20 ) {
			$this->cal_answer_page( 'That link is not valid', 'Nothing was changed.' );
		}

		$rec = get_option( $this->cal_del_key( $bid ) );
		if ( ! is_array( $rec ) || empty( $rec['nonce'] ) ) {
			$this->cal_answer_page( 'Nothing to answer', 'There is no open question about booking #' . $bid . '. Nothing was changed.' );
		}
		if ( ! hash_equals( $this->cal_answer_token( $bid, $rec['nonce'], $ans ), $tok ) ) {
			$this->cal_answer_page( 'That link is not valid', 'Nothing was changed.' );
		}
		if ( ! empty( $rec['answered'] ) ) {
			$this->cal_answer_page(
				'Already answered',
				sprintf( 'Booking #%d was already answered "%s"%s. Nothing was changed this time.', $bid, $rec['answered'], empty( $rec['answered_at'] ) ? '' : ' on ' . $rec['answered_at'] )
			);
		}

		// Consume first. A write that runs twice is worse than a link that dies once.
		$rec['answered']    = $ans;
		$rec['answered_at'] = current_time( 'mysql' );
		update_option( $this->cal_del_key( $bid ), $rec, false );

		global $wpdb;
		$b = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->bookings_table} WHERE id = %d", $bid ) );
		if ( ! $b ) {
			$this->cal_answer_page( 'That booking is gone', 'Booking #' . $bid . ' no longer exists. Nothing was changed.' );
		}
		$label = $this->booking_client_label( (int) $b->client_id, $b );
		$when  = sprintf( '%s %s–%s', $b->booking_date, substr( $b->start_time, 0, 5 ), substr( $b->end_time, 0, 5 ) );

		if ( 'yes' === $ans ) {
			$res = $this->admin_write_booking(
				$bid,
				array( 'status' => 'cancelled' ),
				array(
					'action'         => 'booking.calendar_delete',
					'reason'         => 'Calendar event deleted — cancellation confirmed by Michael',
					'actor'          => 'google-calendar (confirmed)',
					'push_calendar'  => false, // the event is already gone
					'allow_conflict' => true,
					'notify_client'  => false,
				)
			);
			if ( empty( $res['ok'] ) ) {
				$this->cal_answer_page( 'Could not cancel it', isset( $res['message'] ) ? $res['message'] : 'The write was refused. Open wp-admin and cancel it there.' );
			}
			$this->cal_answer_page(
				'Cancelled',
				sprintf( 'Booking #%d — %s, %s — is cancelled and the hours are back on the package. No email was sent to the client.', $bid, $label, $when )
			);
		}

		$res = $this->admin_write_booking(
			$bid,
			array(),
			array(
				'action'            => 'booking.calendar_restore',
				'reason'            => 'Calendar event deleted by mistake — event put back, booking untouched',
				'actor'             => 'google-calendar (confirmed)',
				'push_calendar'     => true,
				'calendar_recreate' => true, // create only; there is nothing left to remove
				'allow_conflict'    => true,
				'notify_client'     => false,
			)
		);
		if ( empty( $res['ok'] ) ) {
			$this->cal_answer_page( 'Could not put it back', isset( $res['message'] ) ? $res['message'] : 'The write was refused. Re-save the booking in wp-admin to rewrite the calendar event.' );
		}
		$this->cal_answer_page(
			'Put back',
			sprintf( 'Booking #%d — %s, %s — stands, and the calendar event is being recreated. Give it a minute, then pull to refresh your calendar.', $bid, $label, $when )
		);
	}

	/** S28: a phone-sized answer page. Ends the request — nothing renders after it. */
	private function cal_answer_page( $title, $body ) {
		status_header( 200 );
		nocache_headers();
		header( 'Content-Type: text/html; charset=utf-8' );
		echo '<!DOCTYPE html><html><head><meta charset="utf-8">'
			. '<meta name="viewport" content="width=device-width,initial-scale=1">'
			. '<meta name="robots" content="noindex,nofollow">'
			. '<title>' . esc_html( $title ) . '</title></head>'
			. '<body style="margin:0;background:#faf6eb;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;">'
			. '<div style="max-width:520px;margin:12vh auto;padding:32px 28px;background:#fff;border-radius:14px;box-shadow:0 4px 20px rgba(0,0,0,.08);">'
			. '<div style="font-size:12px;letter-spacing:3px;text-transform:uppercase;color:#c9a84c;font-weight:700;">MWM Creations &amp; Studios</div>'
			. '<h1 style="font-size:24px;color:#1a1a2e;margin:10px 0 14px;">' . esc_html( $title ) . '</h1>'
			. '<p style="font-size:16px;line-height:1.55;color:#444;margin:0;">' . esc_html( $body ) . '</p>'
			. '<p style="margin:22px 0 0;"><a href="' . esc_url( admin_url( 'admin.php?page=mwm-studio-bookings' ) ) . '" style="color:#0f3460;">Open bookings in wp-admin</a></p>'
			. '</div></body></html>';
		exit;
	}

	public function register_stripe_webhook() {
		register_rest_route( 'mwm-studio/v1', '/stripe-webhook', array(
			'methods'             => 'POST',
			'callback'            => array( $this, 'handle_stripe_webhook' ),
			'permission_callback' => '__return_true', // Stripe sends unsigned requests initially; we verify signature inside.
		) );
	}

	public function handle_stripe_webhook( \WP_REST_Request $request ) {
		$settings = $this->get_settings();
		$secret   = $settings['stripe_webhook_secret'];

		// Read raw body for signature verification.
		$payload   = $request->get_body();
		$sig_header = isset( $_SERVER['HTTP_STRIPE_SIGNATURE'] ) ? $_SERVER['HTTP_STRIPE_SIGNATURE'] : '';

		if ( empty( $secret ) ) {
			error_log( 'MWM Studio Stripe Webhook: No webhook secret configured.' );
			return new \WP_REST_Response( array( 'error' => 'Webhook not configured' ), 500 );
		}

		// Verify Stripe signature (manual HMAC — no Stripe PHP SDK required).
		if ( ! $this->verify_stripe_signature( $payload, $sig_header, $secret ) ) {
			error_log( 'MWM Studio Stripe Webhook: Signature verification failed.' );
			return new \WP_REST_Response( array( 'error' => 'Invalid signature' ), 400 );
		}

		$event = json_decode( $payload, true );
		if ( ! $event || empty( $event['type'] ) ) {
			return new \WP_REST_Response( array( 'error' => 'Invalid payload' ), 400 );
		}

		// Only handle checkout.session.completed
		if ( $event['type'] !== 'checkout.session.completed' ) {
			return new \WP_REST_Response( array( 'received' => true ) );
		}

		$session = $event['data']['object'];

		// Check if this checkout contains our studio package product.
		// For subscriptions, we check the line items via metadata or retrieve later.
		// For payment links, the product info might be in line_items.
		$product_id = $settings['stripe_package_product_id'];

		// Try to identify the product from session metadata or line_items.
		$is_studio_package = false;

		// Method 1: Check if product ID is stored in metadata
		if ( ! empty( $session['metadata']['product_id'] ) && $session['metadata']['product_id'] === $product_id ) {
			$is_studio_package = true;
		}

		// Method 2: Check line_items if expanded (Stripe Payment Links include them)
		if ( ! $is_studio_package && ! empty( $session['line_items']['data'] ) ) {
			foreach ( $session['line_items']['data'] as $item ) {
				if ( ! empty( $item['price']['product'] ) && $item['price']['product'] === $product_id ) {
					$is_studio_package = true;
					break;
				}
			}
		}

		// Method 3: For subscriptions, check the subscription's items
		if ( ! $is_studio_package && $session['mode'] === 'subscription' && ! empty( $session['subscription'] ) ) {
			// We'll accept any checkout.session.completed from our account for now
			// and rely on the product ID match or default behavior.
			// Since we only have one package product, mark it.
			$is_studio_package = true;
		}

		// Method 4: Check amount as fallback ($1,200 = 120000 cents)
		if ( ! $is_studio_package && ! empty( $session['amount_total'] ) && (int) $session['amount_total'] === 120000 ) {
			$is_studio_package = true;
		}

		if ( ! $is_studio_package ) {
			error_log( 'MWM Studio Stripe Webhook: Checkout completed but not for studio package. Ignoring.' );
			return new \WP_REST_Response( array( 'received' => true, 'action' => 'ignored' ) );
		}

		// Extract customer details.
		$customer_email = '';
		$customer_name  = '';

		if ( ! empty( $session['customer_details']['email'] ) ) {
			$customer_email = sanitize_email( $session['customer_details']['email'] );
		} elseif ( ! empty( $session['customer_email'] ) ) {
			$customer_email = sanitize_email( $session['customer_email'] );
		}

		if ( ! empty( $session['customer_details']['name'] ) ) {
			$customer_name = sanitize_text_field( $session['customer_details']['name'] );
		}

		if ( empty( $customer_email ) ) {
			error_log( 'MWM Studio Stripe Webhook: No customer email found in checkout session.' );
			return new \WP_REST_Response( array( 'error' => 'No customer email' ), 400 );
		}

		// Check if client already exists.
		global $wpdb;
		$existing = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$this->clients_table} WHERE email = %s", $customer_email ) );
		if ( $existing ) {
			error_log( 'MWM Studio Stripe Webhook: Client already exists for ' . $customer_email . '. Skipping creation.' );
			return new \WP_REST_Response( array( 'received' => true, 'action' => 'already_exists' ) );
		}

		// Create new client.
		$access_code      = $this->generate_access_code();
		$contract_hours   = (float) $settings['stripe_contract_hours'];
		$contract_months  = (int) $settings['stripe_contract_months'];
		$today            = current_time( 'Y-m-d' );
		$contract_end     = date( 'Y-m-d', strtotime( $today . ' +' . $contract_months . ' months' ) );

		$data = array(
			'name'                => $customer_name ?: 'New Client',
			'email'               => $customer_email,
			'phone'               => '',
			'company'             => '',
			'access_code'         => wp_hash_password( $access_code ),
			'monthly_hours'       => 4.0,
			'contract_hours'      => $contract_hours,
			'contract_start_date' => $today,
			'contract_end_date'   => $contract_end,
			'package_name'        => '4-Hour Studio Package',
			'active'              => 1,
			'notes'               => 'Auto-created via Stripe checkout on ' . $today . '. Stripe session: ' . ( $session['id'] ?? 'unknown' ),
			'created_at'          => current_time( 'mysql' ),
			'updated_at'          => current_time( 'mysql' ),
		);

		$wpdb->insert( $this->clients_table, $data );
		$client_id = $wpdb->insert_id;

		if ( ! $client_id ) {
			error_log( 'MWM Studio Stripe Webhook: Failed to insert client for ' . $customer_email );
			return new \WP_REST_Response( array( 'error' => 'Database insert failed' ), 500 );
		}

		error_log( 'MWM Studio Stripe Webhook: Created client #' . $client_id . ' for ' . $customer_email . ' with access code ' . $access_code );

		// Send welcome email.
		$this->send_welcome_email( $customer_name ?: 'there', $customer_email, $access_code, '4-Hour Studio Package', $contract_hours );

		return new \WP_REST_Response( array(
			'received'  => true,
			'action'    => 'client_created',
			'client_id' => $client_id,
		) );
	}

	/**
	 * Verify Stripe webhook signature without the Stripe PHP SDK.
	 */
	private function verify_stripe_signature( $payload, $sig_header, $secret ) {
		if ( empty( $sig_header ) ) {
			return false;
		}

		// Parse the signature header.
		$parts     = explode( ',', $sig_header );
		$timestamp = null;
		$signatures = array();

		foreach ( $parts as $part ) {
			$kv = explode( '=', trim( $part ), 2 );
			if ( count( $kv ) !== 2 ) continue;

			if ( $kv[0] === 't' ) {
				$timestamp = $kv[1];
			} elseif ( $kv[0] === 'v1' ) {
				$signatures[] = $kv[1];
			}
		}

		if ( ! $timestamp || empty( $signatures ) ) {
			return false;
		}

		// Reject if timestamp is too old (5 minutes tolerance).
		if ( abs( time() - (int) $timestamp ) > 300 ) {
			return false;
		}

		// Compute expected signature.
		$signed_payload    = $timestamp . '.' . $payload;
		$expected_sig      = hash_hmac( 'sha256', $signed_payload, $secret );

		foreach ( $signatures as $sig ) {
			if ( hash_equals( $expected_sig, $sig ) ) {
				return true;
			}
		}

		return false;
	}

	/**
	 * Send the branded welcome email to a new client.
	 */
	private function send_welcome_email( $name, $email, $access_code, $package_name, $total_hours ) {
		$subject = 'Welcome to Your MWM Studio Client Portal';

		$html = $this->get_welcome_email_html( $name, $access_code, $package_name, $total_hours );

		$headers = array(
			'Content-Type: text/html; charset=UTF-8',
			'From: MWM Creations & Studios <info@mwmcreations.com>',
			'Reply-To: MWM Creations & Studios <michael@mwmcreations.com>',
		);

		$sent = wp_mail( $email, $subject, $html, $headers );

		if ( $sent ) {
			error_log( 'MWM Studio: Welcome email sent to ' . $email );
		} else {
			error_log( 'MWM Studio: Failed to send welcome email to ' . $email );
		}

		return $sent;
	}

	/**
	 * Generate the branded welcome email HTML.
	 */
	private function get_welcome_email_html( $name, $access_code, $package_name, $total_hours ) {
		$portal_url = 'https://mwmcreations.com/studio-portal/';
		$hours_text = number_format( $total_hours, 0 ) . ' hours total';

		return '<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width = device-width, initial-scale = 1.0"><title>Welcome to Your MWM Studio Portal</title></head>
<body style="margin:0;padding:0;background-color:#f4f4f4;font-family:Arial,\'Helvetica Neue\',Helvetica,sans-serif;">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">Your exclusive studio portal is live — log in to manage your sessions, view your hours, and book time anytime.</div>
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background-color:#f4f4f4;">
<tr><td align="center" style="padding:20px 10px;">
<table role="presentation" cellpadding="0" cellspacing="0" width="600" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);">
<tr><td bgcolor="#1a1a2e" style="background-color:#1a1a2e;padding:40px 40px 30px;text-align:center;">
  <div style="font-size:32px;font-weight:700;color:#ffffff;letter-spacing:2px;font-family:Georgia,serif;">MWM CREATIONS</div>
  <div style="font-size:13px;color:#c9a84c;letter-spacing:4px;text-transform:uppercase;margin-top:4px;">&amp; Studios</div>
  <table role="presentation" cellpadding="0" cellspacing="0" width="80" style="margin:20px auto 0;"><tr><td style="height:2px;background-color:#c9a84c;"></td></tr></table>
</td></tr>
<tr><td bgcolor="#1a1a2e" style="background-color:#1a1a2e;padding:25px 40px;text-align:center;">
  <div style="font-size:14px;color:#c9a84c;letter-spacing:3px;text-transform:uppercase;font-weight:600;margin-bottom:8px;">Welcome</div>
  <div style="font-size:26px;font-weight:700;color:#ffffff;line-height:1.3;">Your Personal<br>Studio Client Portal</div>
  <div style="font-size:15px;color:#cccccc;margin-top:12px;line-height:1.5;">Book sessions, track your hours, and manage<br>your studio time — all in one place.</div>
</td></tr>
<tr><td style="padding:35px 40px 10px;">
  <div style="font-size:18px;color:#1a1a2e;font-weight:600;">Hi ' . esc_html( $name ) . ',</div>
  <div style="font-size:15px;color:#444444;line-height:1.7;margin-top:12px;">Welcome to MWM Creations &amp; Studios! As part of your studio package, you have access to your personal <strong>Client Portal</strong> — your all-in-one hub to <strong>book studio sessions</strong>, <strong>check your remaining hours</strong>, and <strong>manage your schedule</strong>, all online, anytime, from any device.</div>
  <div style="font-size:15px;color:#444444;line-height:1.7;margin-top:12px;">Below you\'ll find your login credentials and a quick overview of how the portal works.</div>
</td></tr>
<tr><td style="padding:20px 40px;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background-color:#faf6eb;border-radius:10px;border:1px solid #e8ddb5;">
  <tr><td style="padding:25px 30px;">
    <div style="font-size:13px;color:#8b7d3c;letter-spacing:2px;text-transform:uppercase;font-weight:700;margin-bottom:15px;">Your Access Credentials</div>
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:12px;">
    <tr><td width="90" style="font-size:13px;color:#666666;font-weight:600;vertical-align:top;padding-top:2px;">Portal:</td>
    <td style="font-size:15px;"><a href="' . esc_url( $portal_url ) . '" style="color:#0f3460;font-weight:700;text-decoration:none;">mwmcreations.com/studio-portal</a></td></tr></table>
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:12px;">
    <tr><td width="90" style="font-size:13px;color:#666666;font-weight:600;vertical-align:top;padding-top:6px;">Access Code:</td>
    <td><div style="display:inline-block;background-color:#1a1a2e;color:#c9a84c;font-size:20px;font-weight:700;letter-spacing:4px;padding:8px 20px;border-radius:6px;font-family:\'Courier New\',monospace;">' . esc_html( $access_code ) . '</div></td></tr></table>
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
    <tr><td width="90" style="font-size:13px;color:#666666;font-weight:600;vertical-align:top;padding-top:2px;">Package:</td>
    <td style="font-size:15px;color:#1a1a2e;font-weight:600;">' . esc_html( $package_name ) . ' — ' . esc_html( $hours_text ) . '</td></tr></table>
    <div style="font-size:12px;color:#999999;margin-top:15px;font-style:italic;">Keep this code private — it\'s your personal key to the portal.</div>
  </td></tr></table>
</td></tr>
<tr><td align="center" style="padding:10px 40px 25px;">
  <table role="presentation" cellpadding="0" cellspacing="0">
  <tr><td align="center" bgcolor="#c9a84c" style="background-color:#c9a84c;border-radius:8px;">
    <a href="' . esc_url( $portal_url ) . '" target="_blank" style="display:inline-block;padding:16px 50px;font-size:16px;font-weight:700;color:#1a1a2e;text-decoration:none;letter-spacing:1px;">LOG IN TO YOUR PORTAL</a>
  </td></tr></table>
</td></tr>
<tr><td style="padding:5px 40px 20px;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:20px;">
  <tr><td style="border-bottom:2px solid #f0f0f0;padding-bottom:10px;"><div style="font-size:18px;font-weight:700;color:#1a1a2e;">How It Works</div></td></tr></table>
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:18px;">
  <tr><td width="50" valign="top"><div style="width:40px;height:40px;background-color:#1a1a2e;border-radius:50%;text-align:center;line-height:40px;font-size:18px;font-weight:700;color:#c9a84c;">1</div></td>
  <td valign="top" style="padding-left:5px;"><div style="font-size:15px;font-weight:700;color:#1a1a2e;margin-bottom:3px;">Enter Your Access Code</div>
  <div style="font-size:14px;color:#666666;line-height:1.5;">Visit the portal link above and enter your personal access code to log in.</div></td></tr></table>
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:18px;">
  <tr><td width="50" valign="top"><div style="width:40px;height:40px;background-color:#1a1a2e;border-radius:50%;text-align:center;line-height:40px;font-size:18px;font-weight:700;color:#c9a84c;">2</div></td>
  <td valign="top" style="padding-left:5px;"><div style="font-size:15px;font-weight:700;color:#1a1a2e;margin-bottom:3px;">View Your Hours Dashboard</div>
  <div style="font-size:14px;color:#666666;line-height:1.5;">See your contract hours balance — how many hours you\'ve used and how many remain.</div></td></tr></table>
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:5px;">
  <tr><td width="50" valign="top"><div style="width:40px;height:40px;background-color:#1a1a2e;border-radius:50%;text-align:center;line-height:40px;font-size:18px;font-weight:700;color:#c9a84c;">3</div></td>
  <td valign="top" style="padding-left:5px;"><div style="font-size:15px;font-weight:700;color:#1a1a2e;margin-bottom:3px;">Book Your Studio Session</div>
  <div style="font-size:14px;color:#666666;line-height:1.5;">Pick a date and time that works for you and book your session instantly.</div></td></tr></table>
</td></tr>
<tr><td style="padding:15px 40px 20px;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background-color:#f8f9fa;border-radius:10px;border:1px solid #e9ecef;">
  <tr><td style="padding:25px 25px;">
    <div style="font-size:16px;font-weight:700;color:#1a1a2e;margin-bottom:15px;">Studio Reminders</div>
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
    <tr><td width="24" valign="top" style="padding-bottom:10px;color:#c9a84c;font-size:14px;">&#9679;</td>
    <td style="font-size:14px;color:#555555;line-height:1.5;padding-bottom:10px;"><strong>Booking window:</strong> Sessions are available Monday through Friday, 9:00 AM to 4:00 PM.</td></tr>
    <tr><td width="24" valign="top" style="padding-bottom:10px;color:#c9a84c;font-size:14px;">&#9679;</td>
    <td style="font-size:14px;color:#555555;line-height:1.5;padding-bottom:10px;"><strong>Session durations:</strong> Choose from 1, 2, 3, and up to 4-hour sessions based on your project needs.</td></tr>
    <tr><td width="24" valign="top" style="padding-bottom:10px;color:#c9a84c;font-size:14px;">&#9679;</td>
    <td style="font-size:14px;color:#555555;line-height:1.5;padding-bottom:10px;"><strong>Cancellations:</strong> Need to reschedule? You can cancel or reschedule directly from your confirmation email.</td></tr>
    <tr><td width="24" valign="top" style="color:#c9a84c;font-size:14px;">&#9679;</td>
    <td style="font-size:14px;color:#555555;line-height:1.5;"><strong>Over-hours:</strong> If you use more than your allotted hours, additional time is billed at your package rate.</td></tr>
    </table>
  </td></tr></table>
</td></tr>
<tr><td style="padding:15px 40px 25px;">
  <div style="font-size:15px;color:#444444;line-height:1.7;">If you have any questions about the portal or need help getting started, don\'t hesitate to reach out!</div>
  <div style="font-size:15px;color:#444444;line-height:1.7;margin-top:15px;">Looking forward to your first session,</div>
  <div style="margin-top:12px;"><div style="font-size:16px;font-weight:700;color:#1a1a2e;">MWM Creations &amp; Studios</div>
  <div style="font-size:14px;color:#666666;">Orlando, FL</div>
  <div style="font-size:14px;color:#0f3460;margin-top:4px;"><a href="mailto:info@mwmcreations.com" style="color:#0f3460;text-decoration:none;">info@mwmcreations.com</a></div>
  <div style="font-size:14px;color:#0f3460;"><a href="https://mwmcreations.com" style="color:#0f3460;text-decoration:none;">mwmcreations.com</a></div></div>
</td></tr>
<tr><td bgcolor="#1a1a2e" style="background-color:#1a1a2e;padding:25px 40px;text-align:center;">
  <div style="font-size:18px;font-weight:700;color:#ffffff;letter-spacing:1px;font-family:Georgia,serif;">MWM CREATIONS <span style="color:#c9a84c;">&amp;</span> STUDIOS</div>
  <div style="font-size:12px;color:#8888aa;margin-top:8px;line-height:1.5;">Orlando, FL &nbsp;|&nbsp; Storytelling That Moves People</div>
  <table role="presentation" cellpadding="0" cellspacing="0" width="60" style="margin:12px auto 0;"><tr><td style="height:1px;background-color:#c9a84c;"></td></tr></table>
</td></tr>
</table>
</td></tr></table>
</body></html>';
	}

	private function print_admin_css() {
		?>
		<style>
			.mwm-studio-admin .mwm-stat-cards { display:flex; gap:16px; flex-wrap:wrap; margin:20px 0; }
			.mwm-studio-admin .mwm-stat-card { background:#fff; border:1px solid #dcdcde; border-radius:8px; padding:20px 24px; min-width:180px; box-shadow:0 1px 2px rgba(0,0,0,.04); }
			.mwm-studio-admin .mwm-stat-num { display:block; font-size:32px; font-weight:700; color:#1a1a2e; }
			.mwm-studio-admin .mwm-stat-label { display:block; color:#666; margin-top:4px; font-size:13px; }
			.mwm-studio-admin .mwm-card { background:#fff; border:1px solid #dcdcde; border-radius:8px; padding:20px; margin-bottom:20px; max-width:900px; }
			.mwm-studio-admin .mwm-admin-columns { display:flex; gap:24px; align-items:flex-start; flex-wrap:wrap; }
			.mwm-studio-admin .mwm-admin-form-col { flex: 0 0 380px; }
			.mwm-studio-admin .mwm-admin-table-col { flex: 1 1 500px; }
			.mwm-studio-admin .mwm-filters { display:flex; gap:8px; margin:16px 0; flex-wrap:wrap; align-items:center; }
			.mwm-studio-admin label { font-weight:600; display:block; margin-bottom:4px; }
		</style>
		<?php
	}

	/* =========================================================================
	 * FRONTEND PORTAL (HTML/CSS/JS all inline)
	 * ========================================================================= */

	private function render_portal_html() {
		$nonce    = wp_create_nonce( 'mwm_studio_nonce' );
		$ajax_url = admin_url( 'admin-ajax.php' );
		$settings = $this->get_settings();
		?>
		<div id="mwm-studio-app" class="mwm-studio-app" data-nonce="<?php echo esc_attr( $nonce ); ?>" data-ajax-url="<?php echo esc_url( $ajax_url ); ?>">
			<div class="mwm-loading-screen" id="mwm-loading-screen">
				<div class="mwm-spinner"></div>
			</div>
		</div>

		<?php $this->print_portal_css(); ?>

		<script type="text/template" id="mwm-tpl-login">
			<div class="mwm-auth-wrap">
				<div class="mwm-auth-card">
					<div class="mwm-brand">
						<div class="mwm-brand-mark">MWM</div>
						<h1><?php esc_html_e( 'Studio Booking Portal', 'mwm-studio' ); ?></h1>
						<p><?php esc_html_e( 'Log in with your email and access code to book your studio time.', 'mwm-studio' ); ?></p>
					</div>
					<form id="mwm-login-form" autocomplete="off">
						<div class="mwm-field">
							<label><?php esc_html_e( 'Email Address', 'mwm-studio' ); ?></label>
							<input type="email" id="mwm-login-email" required placeholder="you@example.com" />
						</div>
						<div class="mwm-field">
							<label><?php esc_html_e( 'Access Code', 'mwm-studio' ); ?></label>
							<input type="text" id="mwm-login-code" required placeholder="6-character code" maxlength="6" style="text-transform:uppercase;letter-spacing:3px;" />
						</div>
						<div class="mwm-error" id="mwm-login-error" style="display:none;"></div>
						<button type="submit" class="mwm-btn mwm-btn-primary mwm-btn-block" id="mwm-login-btn">
							<span class="mwm-btn-text"><?php esc_html_e( 'Log In', 'mwm-studio' ); ?></span>
						</button>
					</form>
					<div class="mwm-auth-footer">
						<?php esc_html_e( 'Need an access code, or want to upgrade your package?', 'mwm-studio' ); ?>
						<a href="mailto:<?php echo esc_attr( get_option( 'admin_email' ) ); ?>"><?php esc_html_e( 'Contact us', 'mwm-studio' ); ?></a>
					</div>
				</div>
				<div class="mwm-powered-by"><?php esc_html_e( 'Powered by MWM Creations & Studios', 'mwm-studio' ); ?></div>
			</div>
		</script>

		<script type="text/template" id="mwm-tpl-dashboard">
			<div class="mwm-dash-wrap">
				<header class="mwm-dash-header">
					<div>
						<div class="mwm-dash-eyebrow"><?php esc_html_e( 'Welcome back', 'mwm-studio' ); ?></div>
						<h1 id="mwm-client-name">-</h1>
						<div class="mwm-dash-sub" id="mwm-client-package"></div>
					</div>
					<button class="mwm-btn mwm-btn-ghost" id="mwm-logout-btn"><?php esc_html_e( 'Log Out', 'mwm-studio' ); ?></button>
				</header>

				<section class="mwm-hours-card">
					<div class="mwm-hours-info">
						<div class="mwm-hours-label"><?php esc_html_e( 'Contract Hours', 'mwm-studio' ); ?></div>
						<div class="mwm-hours-value"><span id="mwm-hours-used">0</span> <?php esc_html_e( 'of', 'mwm-studio' ); ?> <span id="mwm-hours-total">0</span> <?php esc_html_e( 'hours used', 'mwm-studio' ); ?></div>
						<div class="mwm-progress-track">
							<div class="mwm-progress-fill" id="mwm-hours-progress" style="width:0%;"></div>
						</div>
						<div class="mwm-hours-remaining"><span id="mwm-hours-remaining-num">0</span> <?php esc_html_e( 'hours remaining', 'mwm-studio' ); ?></div>
						<div id="mwm-contract-dates" class="mwm-contract-dates" style="font-size:12px;color:#b8b3d9;margin-top:6px;"></div>
						<div id="mwm-use-by-note" style="display:none;font-size:12px;margin-top:4px;font-weight:600;"></div>
						<div id="mwm-contract-expired" style="display:none;color:#e94560;font-weight:700;margin-top:8px;font-size:14px;"><?php esc_html_e( 'Your contract has expired. Please contact us to renew.', 'mwm-studio' ); ?></div>
					</div>
					<button class="mwm-btn mwm-btn-accent mwm-quick-book-btn" id="mwm-quick-book-btn"><?php esc_html_e( 'Book a Session', 'mwm-studio' ); ?></button>
				</section>

				<section class="mwm-section" id="mwm-upcoming-section">
					<h2><?php esc_html_e( 'Upcoming Bookings', 'mwm-studio' ); ?></h2>
					<div id="mwm-upcoming-list" class="mwm-booking-list">
						<div class="mwm-empty"><?php esc_html_e( 'Loading…', 'mwm-studio' ); ?></div>
					</div>
				</section>

				<section class="mwm-section mwm-book-section" id="mwm-book-section">
					<h2><?php esc_html_e( 'Book a Session', 'mwm-studio' ); ?></h2>
					<p class="mwm-calendly-intro">Pick a date to see available times. Hours come out of your package automatically, and your booking appears under Upcoming Bookings right away.</p>
				<style>
				/* S22 (Aug 9 2026): full month calendar in the portal, matching /book-studio.
				   The old markup was a bare <input type="date"> styled for a DARK page —
				   label colour rgba(255,255,255,.7) rendered white-on-white and the intro
				   line was invisible, which is why this section looked empty. */
				.mwm-cal{max-width:520px;border:1px solid #e5e7eb;border-radius:12px;padding:16px 18px;background:#fff}
				.mwm-cal-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}
				.mwm-cal-label{font-weight:700;font-size:15px;color:#1a1a2e;letter-spacing:.3px}
				.mwm-cal-nav{width:32px;height:32px;border:1px solid #e5e7eb;background:#fff;border-radius:8px;cursor:pointer;font-size:17px;line-height:1;color:#4b5563}
				.mwm-cal-nav:hover{border-color:#7c3aed;color:#7c3aed}
				.mwm-cal-nav[disabled]{opacity:.35;cursor:default;border-color:#e5e7eb;color:#9ca3af}
				.mwm-cal-dow,.mwm-cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}
				.mwm-cal-dow span{text-align:center;font-size:10.5px;letter-spacing:1px;text-transform:uppercase;color:#9ca3af;font-weight:700;padding-bottom:6px}
				.mwm-cal-day{min-height:44px;display:flex;align-items:center;justify-content:center;border-radius:9px;font-size:14px;font-weight:600;border:1px solid transparent;background:#f6f6f8;color:#c3c3cb;cursor:default;padding:0}
				.mwm-cal-blank{background:transparent}
				.mwm-cal-open{background:#f3efff;border-color:#d9cdfa;color:#4c1d95;cursor:pointer;font-family:inherit}
				.mwm-cal-open:hover{background:#e6dcff;border-color:#7c3aed}
				.mwm-cal-picked{background:#7c3aed!important;border-color:#7c3aed!important;color:#fff!important}
				.mwm-cal-loading{grid-column:1/-1;text-align:center;color:#9ca3af;font-size:13px;padding:22px 0}
				.mwm-cal-note{font-size:12.5px;color:#6b7280;margin-top:12px}
				.mwm-slots{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 0}
				.mwm-slot-btn{min-width:90px}
				.mwm-slot-selected{outline:2px solid #7c3aed;background:rgba(124,58,237,.18)!important}
				.mwm-book-field{margin:12px 0}
				.mwm-book-field label{display:block;margin-bottom:6px;color:#4b5563;font-size:13px;font-weight:600}
				.mwm-book-field input,.mwm-book-field select{width:100%;max-width:320px;padding:10px;border-radius:8px;border:1px solid #e5e7eb;background:#fff;color:#1a1a2e;font-family:inherit;font-size:14px}
				.mwm-book-field input:focus,.mwm-book-field select:focus{outline:none;border-color:#7c3aed}
				.mwm-book-error{color:#dc2626;margin-top:10px}
				@media(max-width:560px){.mwm-cal{padding:14px}.mwm-cal-day{min-height:38px;font-size:13px}}
				</style>
				<div id="mwm-native-booking">
					<div id="mwm-cal" class="mwm-cal">
						<div class="mwm-cal-head">
							<button type="button" id="mwm-cal-prev" class="mwm-cal-nav" aria-label="Previous month">&#8249;</button>
							<div id="mwm-cal-label" class="mwm-cal-label"></div>
							<button type="button" id="mwm-cal-next" class="mwm-cal-nav" aria-label="Next month">&#8250;</button>
						</div>
						<div class="mwm-cal-dow"><span>Sun</span><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span></div>
						<div id="mwm-cal-grid" class="mwm-cal-grid"></div>
						<div id="mwm-cal-note" class="mwm-cal-note"></div>
					</div>
					<input type="hidden" id="mwm-book-date">
					<div id="mwm-slots" class="mwm-slots"></div>
					<div id="mwm-book-details" style="display:none">
						<div class="mwm-book-field">
							<label for="mwm-book-duration">Duration</label>
							<select id="mwm-book-duration"></select>
						</div>
						<div class="mwm-book-field">
							<label for="mwm-book-notes">Notes (optional)</label>
							<input type="text" id="mwm-book-notes" maxlength="200" placeholder="Anything we should prepare?">
						</div>
						<button type="button" id="mwm-book-confirm" class="mwm-btn mwm-btn-primary mwm-btn-block">Confirm booking</button>
						<div id="mwm-book-error" class="mwm-book-error" style="display:none"></div>
					</div>
				</div>
				</section>

				<section class="mwm-section">
					<h2 class="mwm-collapsible-header" id="mwm-history-toggle">
						<?php esc_html_e( 'Booking History', 'mwm-studio' ); ?>
						<span class="mwm-chevron">&#9662;</span>
					</h2>
					<div id="mwm-history-list" class="mwm-booking-list mwm-collapsed"></div>
				</section>

				<div class="mwm-contact-footer">
					<?php esc_html_e( 'Want more studio hours?', 'mwm-studio' ); ?>
					<a href="mailto:<?php echo esc_attr( get_option( 'admin_email' ) ); ?>"><?php esc_html_e( 'Contact us about upgrading your package', 'mwm-studio' ); ?></a>
				</div>
				<div class="mwm-powered-by"><?php esc_html_e( 'Powered by MWM Creations & Studios', 'mwm-studio' ); ?></div>
			</div>
		</script>

		<script>
		(function($){
			'use strict';

			var App = {
				root: null,
				nonce: '',
				ajaxUrl: '',
				token: '',
				client: null,
				settings: null,
				todayStr: '',
				selectedSlot: null,

				init: function(){
					this.root = $('#mwm-studio-app');
					this.nonce = this.root.data('nonce');
					this.ajaxUrl = this.root.data('ajax-url');
					this.token = this.getStoredToken();

					var now = new Date();
					this.todayStr = this.fmtDate(now);

					if (this.token) {
						this.showDashboard();
					} else {
						this.showLogin();
					}
				},

				getStoredToken: function(){
					try { return window.localStorage.getItem('mwm_studio_token') || ''; } catch(e){ return ''; }
				},
				storeToken: function(t){
					try { window.localStorage.setItem('mwm_studio_token', t); } catch(e){}
				},
				clearToken: function(){
					try { window.localStorage.removeItem('mwm_studio_token'); } catch(e){}
				},

				fmtDate: function(d){
					var y = d.getFullYear(), m = ('0'+(d.getMonth()+1)).slice(-2), day = ('0'+d.getDate()).slice(-2);
					return y+'-'+m+'-'+day;
				},

				ajax: function(action, data, cb, errCb){
					var self = this;
					data = data || {};
					data.action = action;
					data.nonce = this.nonce;
					if (this.token) data.token = this.token;
					$.post(this.ajaxUrl, data)
						.done(function(resp){
							if (resp && resp.success) {
								cb && cb(resp.data);
							} else {
								if (resp && resp.data && resp.data.code === 'session_expired') {
									self.clearToken();
									self.token = '';
									self.showLogin();
									return;
								}
								errCb && errCb((resp && resp.data && resp.data.message) || 'Something went wrong.');
							}
						})
						.fail(function(){
							errCb && errCb('Network error. Please try again.');
						});
				},

				showLogin: function(){
					this.root.html($('#mwm-tpl-login').html());
					var self = this;
					$('#mwm-login-form').on('submit', function(e){
						e.preventDefault();
						self.doLogin();
					});
				},

				doLogin: function(){
					var self = this;
					var email = $('#mwm-login-email').val();
					var code = $('#mwm-login-code').val();
					var $btn = $('#mwm-login-btn');
					var $err = $('#mwm-login-error');
					$err.hide();
					$btn.prop('disabled', true).addClass('mwm-loading');

					this.ajax('mwm_studio_login', { email: email, access_code: code }, function(data){
						$btn.prop('disabled', false).removeClass('mwm-loading');
						self.token = data.token;
						self.storeToken(data.token);
						self.client = data.client;
						self.showDashboard();
					}, function(msg){
						$btn.prop('disabled', false).removeClass('mwm-loading');
						$err.text(msg).show();
					});
				},

				showDashboard: function(){
					this.root.html($('#mwm-tpl-dashboard').html());
					this.bindDashboardEvents();
					this.loadDashboardData();
				},

				bindDashboardEvents: function(){
					var self = this;
					$('#mwm-logout-btn').on('click', function(){ self.doLogout(); });
					$('#mwm-quick-book-btn').on('click', function(){
						var el = document.getElementById('mwm-book-section');
						if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
					});
					$('#mwm-history-toggle').on('click', function(){
						$('#mwm-history-list').toggleClass('mwm-collapsed');
						$(this).toggleClass('mwm-open');
						if (!$('#mwm-history-list').hasClass('mwm-collapsed') && !self.historyLoaded) {
							self.loadHistory();
						}
					});
				},

				doLogout: function(){
					var self = this;
					this.ajax('mwm_studio_logout', {}, function(){
						self.clearToken();
						self.token = '';
						self.showLogin();
					}, function(){
						self.clearToken();
						self.token = '';
						self.showLogin();
					});
				},

				loadDashboardData: function(){
					var self = this;
					this.ajax('mwm_studio_get_dashboard', {}, function(data){
						self.client = data.client;
						self.settings = data.settings;
						self.renderClientHeader();
						self.renderHours();
						self.renderUpcoming(data.upcoming);
						self.initBooking();
					}, function(msg){
						self.showToastError(msg);
					});
				},

				renderClientHeader: function(){
					$('#mwm-client-name').text(this.client.name);
					var pkg = this.client.package_name ? this.client.package_name : '';
					$('#mwm-client-package').text(pkg);
				},

				renderHours: function(){
					var used = parseFloat(this.client.hours_used) || 0;
					var total = parseFloat(this.client.contract_hours) || 0;
					var remaining = parseFloat(this.client.hours_remaining) || 0;
					var pct = total > 0 ? Math.min(100, (used/total)*100) : 0;

					$('#mwm-hours-used').text(used.toFixed(used % 1 === 0 ? 0 : 1));
					$('#mwm-hours-total').text(total.toFixed(total % 1 === 0 ? 0 : 1));
					$('#mwm-hours-remaining-num').text(remaining.toFixed(remaining % 1 === 0 ? 0 : 1));
					$('#mwm-hours-progress').css('width', pct + '%');

					if (pct >= 100) {
						$('#mwm-hours-progress').css('background', '#e94560');
					} else if (pct >= 75) {
						$('#mwm-hours-progress').css('background', 'linear-gradient(90deg,#8247f5,#e94560)');
					} else {
						$('#mwm-hours-progress').css('background', '#8247f5');
					}

					// Show contract date range
					var start = this.client.contract_start;
					var end = this.client.contract_end;
					var status = this.client.contract_status;
					if (start && end) {
						var startDate = new Date(start + 'T00:00:00');
						var endDate = new Date(end + 'T00:00:00');
						var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
						var startStr = months[startDate.getMonth()] + ' ' + startDate.getDate() + ', ' + startDate.getFullYear();
						var endStr = months[endDate.getMonth()] + ' ' + endDate.getDate() + ', ' + endDate.getFullYear();
						$('#mwm-contract-dates').text('Contract: ' + startStr + ' – ' + endStr).show();
						// S8.6: use-by date — unused hours expire on contract_end (30-day grace policy)
						var todayUB = new Date(); todayUB.setHours(0,0,0,0);
						if (status !== 'expired' && endDate >= todayUB) {
							var daysLeftUB = Math.round((endDate - todayUB) / 86400000);
							var useByTxt = 'Hours must be used by ' + endStr + ' — unused hours expire.';
							if (daysLeftUB <= 30) {
								useByTxt = '\u26A0 ' + daysLeftUB + ' day' + (daysLeftUB === 1 ? '' : 's') + ' left — hours expire ' + endStr + '.';
							}
							$('#mwm-use-by-note').text(useByTxt).css('color', daysLeftUB <= 30 ? '#e94560' : '#b8b3d9').show();
						}
					}

					// Show expired warning
					if (status === 'expired') {
						$('#mwm-contract-expired').show();
						$('#mwm-quick-book-btn').hide();
					}
				},

				renderUpcoming: function(list){
					var $list = $('#mwm-upcoming-list');
					if (!list || !list.length) {
						$list.html('<div class="mwm-empty"><?php echo esc_js( __( 'No upcoming bookings. Book your next session below!', 'mwm-studio' ) ); ?></div>');
						return;
					}
					var self = this;
					var html = '';
					list.forEach(function(b){
						html += '<div class="mwm-booking-item mwm-status-confirmed">';
						html += '  <div class="mwm-booking-main">';
						html += '    <div class="mwm-booking-date">' + self.escHtml(b.date_label) + '</div>';
						html += '    <div class="mwm-booking-time">' + self.escHtml(b.start_time) + ' &ndash; ' + self.escHtml(b.end_time) + ' &middot; ' + b.duration_hours + 'h</div>';
						html += '  </div>';
						if (b.can_cancel) {
							html += '  <button class="mwm-btn mwm-btn-outline-danger mwm-cancel-btn" data-id="' + b.id + '"><?php echo esc_js( __( 'Cancel', 'mwm-studio' ) ); ?></button>';
						} else {
							html += '  <span class="mwm-badge-locked"><?php echo esc_js( __( 'Locked', 'mwm-studio' ) ); ?></span>';
						}
						html += '</div>';
					});
					$list.html(html);
					$list.find('.mwm-cancel-btn').on('click', function(){
						self.cancelBooking($(this).data('id'), $(this));
					});
				},

				cancelBooking: function(id, $btn){
					var self = this;
					if (!confirm('<?php echo esc_js( __( 'Cancel this booking?', 'mwm-studio' ) ); ?>')) return;
					$btn.prop('disabled', true).text('<?php echo esc_js( __( 'Cancelling…', 'mwm-studio' ) ); ?>');
					this.ajax('mwm_studio_cancel_booking', { booking_id: id }, function(){
						self.loadDashboardData();
						self.historyLoaded = false;
					}, function(msg){
						alert(msg);
						$btn.prop('disabled', false).text('<?php echo esc_js( __( 'Cancel', 'mwm-studio' ) ); ?>');
					});
				},

				loadHistory: function(){
					var self = this;
					var $list = $('#mwm-history-list');
					$list.html('<div class="mwm-empty"><?php echo esc_js( __( 'Loading…', 'mwm-studio' ) ); ?></div>');
					this.ajax('mwm_studio_get_history', {}, function(data){
						self.historyLoaded = true;
						if (!data.history.length) {
							$list.html('<div class="mwm-empty"><?php echo esc_js( __( 'No past bookings yet.', 'mwm-studio' ) ); ?></div>');
							return;
						}
						var html = '';
						data.history.forEach(function(b){
							html += '<div class="mwm-booking-item mwm-status-' + b.status + '">';
							html += '  <div class="mwm-booking-main">';
							html += '    <div class="mwm-booking-date">' + self.escHtml(b.date_label) + '</div>';
							html += '    <div class="mwm-booking-time">' + self.escHtml(b.start_time) + ' &ndash; ' + self.escHtml(b.end_time) + ' &middot; ' + b.duration_hours + 'h</div>';
							html += '  </div>';
							html += '  <span class="mwm-status-pill mwm-status-pill-' + b.status + '">' + b.status + '</span>';
							html += '</div>';
						});
						$list.html(html);
					}, function(msg){
						$list.html('<div class="mwm-empty">' + self.escHtml(msg) + '</div>');
					});
				},

				/* Calendly Integration */

				initBooking: function() {
					var self = this;
					if (!this.client) return;
					var g = document.getElementById('mwm-cal-grid');
					if (!g || g.dataset.mwmBound) return;
					g.dataset.mwmBound = '1';
					var t = new Date();
					this.calY = t.getFullYear();
					this.calM = t.getMonth() + 1;
					this.calFirstY = this.calY;
					this.calFirstM = this.calM;
					this.calDays = [];
					$('#mwm-cal-prev').on('click', function(){ self.moveMonth(-1); });
					$('#mwm-cal-next').on('click', function(){ self.moveMonth(1); });
					$('#mwm-book-confirm').on('click', function(){ self.confirmBooking(); });
					this.loadMonth();
				},

				monthName: function(m) {
					return ['January','February','March','April','May','June','July',
					        'August','September','October','November','December'][m - 1] || '';
				},

				moveMonth: function(n) {
					this.calM += n;
					if (this.calM < 1) { this.calM = 12; this.calY--; }
					if (this.calM > 12) { this.calM = 1; this.calY++; }
					this.loadMonth();
				},

				/* S22: availability comes from mwm_studio_rental_month — the SAME endpoint
				   the /book-studio month calendar uses, which derives from
				   get_available_slots (pending holds + Google Calendar busy blocks).
				   One source of truth: a day is open here only if it is open there.
				   duration:1 is the loosest filter, which is what a day picker wants —
				   the slot list narrows it afterwards. */
				loadMonth: function() {
					var self = this;
					var atStart = (this.calY === this.calFirstY && this.calM === this.calFirstM);
					$('#mwm-cal-prev').prop('disabled', atStart);
					$('#mwm-cal-label').text(this.monthName(this.calM) + ' ' + this.calY);
					$('#mwm-cal-grid').html('<div class="mwm-cal-loading">Checking availability…</div>');
					$('#mwm-cal-note').text('');
					$('#mwm-slots').empty();
					$('#mwm-book-details').hide();
					this.ajax('mwm_studio_rental_month', { year: this.calY, month: this.calM, duration: 1 }, function(data){
						self.calDays = (data && data.days) || [];
						self.renderCal();
					}, function(msg){
						$('#mwm-cal-grid').empty();
						$('#mwm-cal-note').text(msg || 'Could not load availability — please try again in a moment.');
					});
				},

				renderCal: function() {
					var self = this;
					var firstDow = new Date(this.calY, this.calM - 1, 1).getDay();
					var total    = new Date(this.calY, this.calM, 0).getDate();
					var open = {};
					for (var i = 0; i < this.calDays.length; i++) { open[String(this.calDays[i])] = 1; }
					var html = '';
					for (var b = 0; b < firstDow; b++) { html += '<span class="mwm-cal-day mwm-cal-blank"></span>'; }
					for (var d = 1; d <= total; d++) {
						var iso = this.calY + '-' + ('0' + this.calM).slice(-2) + '-' + ('0' + d).slice(-2);
						if (open[iso]) {
							html += '<button type="button" class="mwm-cal-day mwm-cal-open" data-date="' + iso + '">' + d + '</button>';
						} else {
							html += '<span class="mwm-cal-day mwm-cal-closed">' + d + '</span>';
						}
					}
					$('#mwm-cal-grid').html(html);
					var n = this.calDays.length;
					$('#mwm-cal-note').text(n
						? n + (n === 1 ? ' day' : ' days') + ' open this month — pick one to see times.'
						: 'No open days this month. Use the arrow to look at the next one.');
					$('#mwm-cal-grid .mwm-cal-open').on('click', function(){
						$('#mwm-cal-grid .mwm-cal-open').removeClass('mwm-cal-picked');
						$(this).addClass('mwm-cal-picked');
						var iso = String($(this).data('date'));
						$('#mwm-book-date').val(iso);
						self.loadSlots(iso);
					});
				},

				fmtDate: function(iso) {
					if (!iso) { return 'the end of your contract'; }
					var d = new Date(String(iso) + 'T00:00:00');
					if (isNaN(d.getTime())) { return String(iso); }
					var m = ['January','February','March','April','May','June','July','August','September','October','November','December'];
					return m[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
				},

				loadSlots: function(date) {
					var self = this;
					this.selectedSlot = null;
					$('#mwm-book-details').hide();
					$('#mwm-book-error').hide();
					$('#mwm-slots').html('<div class="mwm-empty">Checking availability…</div>');
					this.ajax('mwm_studio_get_available_slots', { date: date }, function(data){
						// S29: every one of these used to fall through to
						// "No available times on this date — try another day",
						// which is false for three of them and is why a client
						// with a valid contract concluded we were fully booked.
						var reason = (data && data.reason) || '';
						if (reason === 'availability_unavailable') {
							$('#mwm-slots').html('<div class="mwm-empty">Booking is temporarily unavailable — please try again in a few minutes, or message us on WhatsApp.</div>');
							return;
						}
						if (reason === 'out_of_range') {
							var msg;
							if (data.kind === 'past') {
								msg = 'That date has already passed — please pick a date from today onwards.';
							} else {
								msg = 'Your hours must be used by ' + self.fmtDate(data.max_date) + ', so later dates cannot be booked here. If you need more time, reply to your welcome email or call (813) 503-1224 — we can usually help.';
							}
							$('#mwm-slots').html('<div class="mwm-empty">' + self.escHtml(msg) + '</div>');
							return;
						}
						if (reason === 'contract_expired') {
							$('#mwm-slots').html('<div class="mwm-empty">' + self.escHtml('This package ended on ' + self.fmtDate(data.contract_end) + '. Call (813) 503-1224 or reply to your welcome email and we will get you booked.') + '</div>');
							return;
						}
						if (reason === 'no_hours') {
							$('#mwm-slots').html('<div class="mwm-empty">' + self.escHtml('You have no studio hours left on this package. Call (813) 503-1224 or reply to your welcome email to add more.') + '</div>');
							return;
						}
						var slots = (data && data.slots) || [];
						if (!slots.length) {
							$('#mwm-slots').html('<div class="mwm-empty">No available times on this date — try another day.</div>');
							return;
						}
						var html = '';
						for (var i = 0; i < slots.length; i++) {
							html += '<button type="button" class="mwm-btn mwm-btn-ghost mwm-slot-btn" data-start="' + self.escHtml(String(slots[i].start)) + '" data-max="' + (parseInt(slots[i].max_duration, 10) || 1) + '">' + self.escHtml(self.fmt12(String(slots[i].start))) + '</button>';
						}
						$('#mwm-slots').html(html);
						$('#mwm-slots .mwm-slot-btn').on('click', function(){
							$('#mwm-slots .mwm-slot-btn').removeClass('mwm-slot-selected');
							$(this).addClass('mwm-slot-selected');
							self.selectedSlot = { start: String($(this).data('start')), max: parseInt($(this).data('max'), 10) || 1 };
							var sel = $('#mwm-book-duration').empty();
							for (var d2 = 1; d2 <= self.selectedSlot.max; d2++) {
								sel.append($('<option>').val(d2).text(d2 + (d2 === 1 ? ' hour' : ' hours')));
							}
							$('#mwm-book-details').show();
						});
					}, function(msg){
						$('#mwm-slots').html('<div class="mwm-empty">' + self.escHtml(msg) + '</div>');
					});
				},

				confirmBooking: function() {
					var self = this;
					if (!this.selectedSlot) return;
					$('#mwm-book-error').hide();
					var btn = $('#mwm-book-confirm').prop('disabled', true).text('Booking…');
					this.ajax('mwm_studio_create_booking', {
						date: $('#mwm-book-date').val(),
						start_time: this.selectedSlot.start,
						duration: $('#mwm-book-duration').val(),
						notes: $('#mwm-book-notes').val()
					}, function(data){
						btn.prop('disabled', false).text('Confirm booking');
						$('#mwm-book-details').hide();
						$('#mwm-slots').empty();
						$('#mwm-book-date').val('');
						$('#mwm-book-notes').val('');
						$('#mwm-cal-grid .mwm-cal-open').removeClass('mwm-cal-picked');
						self.selectedSlot = null;
						self.loadMonth();
						self.loadDashboardData();
						self.showToast((data && data.message) ? data.message : 'Session booked! It now appears under Upcoming Bookings.');
					}, function(msg){
						btn.prop('disabled', false).text('Confirm booking');
						$('#mwm-book-error').text(msg).show();
					});
				},

				showToast: function(msg) {
					var toast = $('<div class="mwm-toast">' + msg + '</div>');
					this.root.append(toast);
					setTimeout(function(){ toast.addClass('mwm-toast-show'); }, 50);
					setTimeout(function(){ toast.removeClass('mwm-toast-show'); setTimeout(function(){ toast.remove(); }, 300); }, 4000);
				},

				showToastError: function(msg){
					console.error(msg);
				},

				fmt12: function(t){
					var p = String(t).split(':');
					var h = parseInt(p[0], 10);
					if (isNaN(h)) { return t; }
					return ((h % 12) || 12) + ':' + (p[1] || '00') + ' ' + (h >= 12 ? 'PM' : 'AM');
				},
				escHtml: function(str){
					return $('<div>').text(str == null ? '' : str).html();
				}
			};

			$(function(){ App.init(); });

		})(jQuery);
		</script>
		<?php
	}

	private function print_portal_css() {
		?>
		<style>
			.mwm-studio-app, .mwm-studio-app * { box-sizing: border-box; }
			.mwm-studio-app {
				font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
				color: #1a1a2e;
				line-height: 1.5;
				max-width: 960px;
				margin: 0 auto;
			}
			.mwm-studio-app a { text-decoration: none; }
			.mwm-loading-screen { display:flex; align-items:center; justify-content:center; min-height: 300px; }
			.mwm-spinner {
				width: 40px; height: 40px; border-radius: 50%;
				border: 4px solid rgba(130,71,245,.15); border-top-color: #8247f5;
				animation: mwm-spin 0.8s linear infinite;
			}
			@keyframes mwm-spin { to { transform: rotate(360deg); } }

			/* Auth screen */
			.mwm-auth-wrap {
				min-height: 520px;
				display: flex; flex-direction: column; align-items: center; justify-content: center;
				background: radial-gradient(circle at top, #232042 0%, #14131f 65%);
				border-radius: 16px;
				padding: 48px 20px;
			}
			.mwm-auth-card {
				background: #ffffff;
				border-radius: 16px;
				padding: 40px 36px;
				width: 100%;
				max-width: 400px;
				box-shadow: 0 20px 60px rgba(0,0,0,.35);
			}
			.mwm-brand { text-align: center; margin-bottom: 28px; }
			.mwm-brand-mark {
				display: inline-flex; align-items:center; justify-content:center;
				width: 56px; height: 56px; border-radius: 14px;
				background: linear-gradient(135deg,#8247f5,#e94560);
				color: #fff; font-weight: 800; font-size: 16px; letter-spacing: 1px;
				margin-bottom: 16px;
			}
			.mwm-brand h1 { font-size: 22px; margin: 0 0 6px; font-weight: 700; color: #1a1a2e; }
			.mwm-brand p { font-size: 14px; color: #6b6b80; margin: 0; }

			.mwm-field { margin-bottom: 18px; }
			.mwm-field label { display:block; font-size: 13px; font-weight: 600; margin-bottom: 6px; color:#3d3d52; }
			.mwm-field input, .mwm-field textarea {
				width: 100%; padding: 12px 14px; border-radius: 10px;
				border: 1.5px solid #e3e2ef; font-size: 15px; font-family: inherit;
				transition: border-color .15s ease, box-shadow .15s ease;
				background: #fbfbfe;
			}
			.mwm-field input:focus, .mwm-field textarea:focus {
				outline: none; border-color: #8247f5; box-shadow: 0 0 0 3px rgba(130,71,245,.15); background:#fff;
			}

			.mwm-btn {
				display: inline-flex; align-items:center; justify-content:center; gap:8px;
				border: none; border-radius: 10px; padding: 13px 22px;
				font-size: 15px; font-weight: 600; cursor: pointer; font-family: inherit;
				transition: transform .12s ease, box-shadow .12s ease, background .15s ease, opacity .15s ease;
			}
			.mwm-btn:active { transform: translateY(1px); }
			.mwm-btn:disabled { opacity: .5; cursor: not-allowed; }
			.mwm-btn-block { width: 100%; }
			.mwm-btn-primary { background: #8247f5; color: #fff; box-shadow: 0 6px 16px rgba(130,71,245,.35); }
			.mwm-btn-primary:hover:not(:disabled) { background: #7238e8; }
			.mwm-btn-accent { background: #e94560; color: #fff; box-shadow: 0 6px 16px rgba(233,69,96,.35); }
			.mwm-btn-accent:hover:not(:disabled) { background: #d5354f; }
			.mwm-btn-ghost { background: transparent; color:#3d3d52; border: 1.5px solid #e3e2ef; }
			.mwm-btn-ghost:hover { background:#f5f4fb; }
			.mwm-btn-outline-danger { background:#fff; color:#e94560; border:1.5px solid #f3c9d1; padding: 8px 14px; font-size:13px; }
			.mwm-btn-outline-danger:hover { background:#fff5f6; }

			.mwm-error {
				background: #fdecee; color:#c62828; border:1px solid #f3c9d1; border-radius:10px;
				padding: 10px 14px; font-size: 13px; margin-bottom: 16px;
			}
			.mwm-auth-footer { text-align:center; font-size: 13px; color:#6b6b80; margin-top: 20px; }
			.mwm-auth-footer a { color:#8247f5; font-weight:600; margin-left: 4px; }
			.mwm-powered-by { text-align:center; color: rgba(255,255,255,.5); font-size: 12px; margin-top: 24px; letter-spacing:.3px; }

			/* Dashboard */
			.mwm-dash-wrap { padding: 8px 4px 40px; }
			.mwm-dash-header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-bottom: 24px; flex-wrap:wrap; }
			.mwm-dash-eyebrow { font-size:12px; text-transform:uppercase; letter-spacing:1px; color:#8247f5; font-weight:700; margin-bottom:4px; }
			.mwm-dash-header h1 { font-size: 28px; margin: 0; font-weight: 800; color:#1a1a2e; }
			.mwm-dash-sub { color:#6b6b80; font-size: 14px; margin-top:4px; }

			.mwm-hours-card {
				background: linear-gradient(135deg,#1a1a2e,#232042);
				border-radius: 18px; padding: 28px; color:#fff;
				display:flex; align-items:center; justify-content:space-between; gap: 24px; flex-wrap: wrap;
				margin-bottom: 28px;
				box-shadow: 0 10px 30px rgba(26,26,46,.25);
			}
			.mwm-hours-info { flex: 1 1 260px; }
			.mwm-hours-label { font-size:12px; text-transform:uppercase; letter-spacing:1px; color:#b8b3d9; font-weight:700; margin-bottom:6px; }
			.mwm-hours-value { font-size: 20px; font-weight:700; margin-bottom: 12px; }
			.mwm-progress-track { background: rgba(255,255,255,.12); border-radius: 999px; height: 10px; overflow:hidden; }
			.mwm-progress-fill { height: 100%; background:#8247f5; border-radius:999px; transition: width .4s ease; }
			.mwm-hours-remaining { margin-top: 10px; font-size: 13px; color:#b8b3d9; }
			.mwm-quick-book-btn { flex-shrink: 0; }

			.mwm-section { margin-bottom: 32px; }
			.mwm-section h2 { font-size: 18px; font-weight: 700; margin: 0 0 14px; color:#1a1a2e; }

			.mwm-booking-list { display:flex; flex-direction:column; gap:10px; }
			.mwm-booking-item {
				display:flex; align-items:center; justify-content:space-between; gap:12px;
				background:#fff; border:1.5px solid #ecebf5; border-radius:12px; padding:14px 18px;
				border-left: 4px solid #2e7d32;
				flex-wrap: wrap;
			}
			.mwm-status-cancelled { border-left-color:#e94560; }
			.mwm-status-completed { border-left-color:#9a9ab0; }
			.mwm-booking-date { font-weight:700; font-size:14px; color:#1a1a2e; }
			.mwm-booking-time { font-size:13px; color:#6b6b80; margin-top:2px; }
			.mwm-badge-locked { font-size:12px; color:#9a9ab0; font-weight:600; }
			.mwm-status-pill { font-size:11px; font-weight:700; text-transform:uppercase; padding:4px 10px; border-radius:999px; letter-spacing:.4px; }
			.mwm-status-pill-completed { background:#f1f0f7; color:#6b6b80; }
			.mwm-status-pill-cancelled { background:#fdecee; color:#c62828; }
			.mwm-status-pill-confirmed { background:#e8f5e9; color:#2e7d32; }
			.mwm-empty { color:#9a9ab0; font-size: 14px; padding: 20px; text-align:center; background:#fafafe; border-radius:12px; border:1.5px dashed #e3e2ef; }

			/* Calendar */
			.mwm-calendar-wrap { background:#fff; border:1.5px solid #ecebf5; border-radius:14px; padding:18px; }
			.mwm-calendar-nav { display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; }
			.mwm-cal-month-label { font-weight:700; font-size:16px; }
			.mwm-cal-nav-btn { border:1.5px solid #e3e2ef; background:#fff; border-radius:8px; width:34px; height:34px; cursor:pointer; font-size:15px; color:#3d3d52; }
			.mwm-cal-nav-btn:hover { background:#f5f4fb; }
			.mwm-calendar-grid { display:grid; grid-template-columns: repeat(7,1fr); gap:6px; }
			.mwm-calendar-dow { margin-bottom:6px; font-size:11px; font-weight:700; text-transform:uppercase; color:#9a9ab0; text-align:center; }
			.mwm-cal-day {
				aspect-ratio: 1/1; display:flex; align-items:center; justify-content:center;
				border-radius:10px; font-size:14px; cursor:pointer; font-weight:600; color:#3d3d52;
				background:#fafafe; transition: background .12s ease, color .12s ease, transform .1s ease;
			}
			.mwm-cal-day:hover:not(.mwm-cal-day-disabled):not(.mwm-cal-day-empty) { background:#efeafd; color:#8247f5; }
			.mwm-cal-day-empty { background:transparent; cursor:default; }
			.mwm-cal-day-disabled { color:#d4d3e0; cursor:not-allowed; background:transparent; }
			.mwm-cal-day-today { box-shadow: inset 0 0 0 2px #e94560; }
			.mwm-cal-day-selected { background:#8247f5 !important; color:#fff !important; }

			.mwm-slots-wrap { margin-top: 20px; background:#fff; border:1.5px solid #ecebf5; border-radius:14px; padding:20px; }
			.mwm-slots-wrap h3 { margin:0 0 14px; font-size:15px; font-weight:700; }
			.mwm-duration-label { font-size:13px; font-weight:700; color:#3d3d52; margin-bottom:8px; }
			.mwm-duration-options { display:flex; gap:8px; margin-bottom:18px; flex-wrap:wrap; }
			.mwm-duration-btn {
				border:1.5px solid #e3e2ef; background:#fff; border-radius:8px; padding:8px 16px;
				font-weight:700; cursor:pointer; font-size:14px; color:#3d3d52;
			}
			.mwm-duration-btn:hover { border-color:#8247f5; }
			.mwm-duration-active { background:#8247f5; border-color:#8247f5; color:#fff; }

			.mwm-slots-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(84px,1fr)); gap:8px; }
			.mwm-slot-btn {
				border:1.5px solid #e3e2ef; background:#fafafe; border-radius:8px; padding:10px 6px;
				font-weight:600; cursor:pointer; font-size:13px; color:#3d3d52; transition: all .12s ease;
			}
			.mwm-slot-btn:hover { border-color:#8247f5; background:#efeafd; }
			.mwm-slot-active { background:#8247f5; border-color:#8247f5; color:#fff; }

			.mwm-collapsible-header { cursor:pointer; display:flex; align-items:center; justify-content:space-between; user-select:none; }
			.mwm-chevron { transition: transform .2s ease; color:#9a9ab0; }
			.mwm-collapsible-header.mwm-open .mwm-chevron { transform: rotate(180deg); }
			.mwm-collapsed { display:none; }

			.mwm-contact-footer { text-align:center; font-size:13px; color:#6b6b80; margin-top:8px; }
			.mwm-contact-footer a { color:#8247f5; font-weight:700; margin-left:4px; }

			/* Calendly embed */
			.mwm-calendly-intro { color: #6b7280; margin-bottom: 16px; font-size: 14px; }
			.mwm-calendly-container { border-radius: 12px; overflow: hidden; background: #1a1a2e; }
			.mwm-calendly-container .calendly-inline-widget, #mwm-calendly-widget { min-height: 1400px; }

			/* Toast notification */
			.mwm-toast { position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%) translateY(20px); background: #7c3aed; color: #fff; padding: 14px 28px; border-radius: 10px; font-size: 14px; font-weight: 600; z-index: 10001; opacity: 0; transition: all 0.3s ease; pointer-events: none; box-shadow: 0 4px 20px rgba(124,58,237,0.5); }
			.mwm-toast-show { opacity: 1; transform: translateX(-50%) translateY(0); }

			@media (max-width: 600px) {
				.mwm-auth-card { padding: 30px 22px; }
				.mwm-dash-header h1 { font-size: 22px; }
				.mwm-hours-card { flex-direction: column; align-items: stretch; }
				.mwm-quick-book-btn { width: 100%; }
				.mwm-slots-grid { grid-template-columns: repeat(auto-fill, minmax(70px,1fr)); }
				.mwm-booking-item { flex-direction: column; align-items: flex-start; }
			}
		</style>
		<?php
	}
}

MWM_Studio_Booking::instance();
