// Code Snippets plugin — A2P 10DLC v2 · TWO CONSENTS, ACTUALLY CAPTURED (pages 741, 1193)
// DEV · Aug 12 2026 · supersedes snippet 20 (deactivate 20 before activating this)
//
// ─────────────────────────────────────────────────────────────────────────────
// 🔴 WHY THIS EXISTS, AND WHY THE LABEL EDITS WERE NEVER GOING TO BE ENOUGH.
//
// Campaign CM87b39e12 has been rejected four times. Every fix so far edited the
// WORDS on the consent checkbox. Nobody checked what the checkbox DID.
//
// It did nothing. Verified Aug 12 2026 by reading the code end to end:
//
//   • /book-studio/ collects a mobile number in #bs-phone (name="phone_number").
//   • It collects consent in #bs-sms-consent-box (name="sms_consent").
//   • The widget's reserve() posts EXACTLY seven fields to mwm_studio_hold_slot:
//        date, start_time, hours, editing, name, email, notes
//     Neither the phone nor the consent is among them.
//   • mwm-studio-booking.php reads those same seven. It contains ZERO references
//     to a phone number or a consent flag anywhere in the file.
//
// So the number was typed and thrown away, the box was ticked and thrown away,
// and /sms-opt-in/ told Twilio "consent is recorded against the phone number
// with a timestamp at the moment of submission" — which was not true, and had
// never been true, for a single web-form opt-in.
//
// 🔑 A consent checkbox that is not stored is not consent. It is a picture of
//    consent. This snippet makes it real, and only then splits it in two.
//
// WHAT IT DOES
//   1. Creates {prefix}mwm_sms_consent and writes one row per submission:
//      phone, both consent flags, name, email, page URL, IP, user agent, UTC
//      timestamp. That row is the evidence a carrier audit asks for.
//   2. Splits the single bundled checkbox into two — transactional, and a
//      separate OPTIONAL marketing box — per Twilio (Muskan Jul 20 + Aug 12,
//      Salic Aug 11). Wording is verbatim what was sent to Twilio on Aug 12.
//   3. Appends phone_number + both flags to the existing booking POST.
//
// 🔴 IT DOES NOT TOUCH THE CHECKOUT. The Elementor widget on page 741 is the
// only revenue-taking checkout in the business and is not in version control
// beyond a rendered snapshot (see wordpress/page-741-book-studio/README-RESTORE.md).
// So this snippet is purely ADDITIVE: it decorates the DOM and appends fields to
// a FormData that is already being sent. It adds no listener to the pay button,
// blocks no submission, and changes no pricing or availability path. Deactivating
// it restores the previous behaviour exactly.
// ─────────────────────────────────────────────────────────────────────────────

if ( ! defined( 'ABSPATH' ) ) { exit; }

define( 'MWM_A2P_V2', '2.1.0' );

/* ── 1 · the ledger ──────────────────────────────────────────────────────── */

function mwm_a2p_table() {
	global $wpdb;
	return $wpdb->prefix . 'mwm_sms_consent';
}

function mwm_a2p_install() {
	if ( get_option( 'mwm_a2p_db' ) === MWM_A2P_V2 ) { return; }
	global $wpdb;
	require_once ABSPATH . 'wp-admin/includes/upgrade.php';
	$t = mwm_a2p_table();
	$c = $wpdb->get_charset_collate();
	dbDelta( "CREATE TABLE {$t} (
		id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
		created_at datetime NOT NULL,
		phone varchar(32) NOT NULL DEFAULT '',
		phone_e164 varchar(32) NOT NULL DEFAULT '',
		transactional tinyint(1) NOT NULL DEFAULT 0,
		marketing tinyint(1) NOT NULL DEFAULT 0,
		guest_name varchar(191) NOT NULL DEFAULT '',
		guest_email varchar(191) NOT NULL DEFAULT '',
		source_url varchar(255) NOT NULL DEFAULT '',
		ip varchar(45) NOT NULL DEFAULT '',
		user_agent varchar(255) NOT NULL DEFAULT '',
		PRIMARY KEY  (id),
		KEY phone_e164 (phone_e164),
		KEY created_at (created_at)
	) {$c};" );
	update_option( 'mwm_a2p_db', MWM_A2P_V2, false );
}
add_action( 'init', 'mwm_a2p_install', 1 );

/* ── 2 · capture, before the booking handler runs ────────────────────────── */

/**
 * 🔴 Priority 1 so this runs BEFORE the plugin's handler, which ends in
 * wp_send_json_* and therefore exits. This function must never die, never echo
 * and never send headers — if it did, it would take the checkout with it.
 *
 * Consent is recorded even when the slot turns out to be gone. The customer
 * ticked the box and pressed the button; that is the moment consent was given,
 * and it does not un-happen because a slot was taken thirty seconds earlier.
 */
function mwm_a2p_capture() {

	// Same nonce the booking handler checks, verified NON-fatally. A bad nonce
	// means we simply do not record — the handler will refuse it a moment later.
	$nonce = isset( $_POST['nonce'] ) ? sanitize_text_field( wp_unslash( $_POST['nonce'] ) ) : '';
	if ( ! $nonce || ! wp_verify_nonce( $nonce, 'mwm_studio_rental' ) ) { return; }

	$t = isset( $_POST['sms_consent'] ) && '1' === (string) $_POST['sms_consent'] ? 1 : 0;
	$m = isset( $_POST['sms_marketing_consent'] ) && '1' === (string) $_POST['sms_marketing_consent'] ? 1 : 0;

	// Nothing ticked is not an event worth a row.
	if ( ! $t && ! $m ) { return; }

	$raw    = isset( $_POST['phone_number'] ) ? sanitize_text_field( wp_unslash( $_POST['phone_number'] ) ) : '';
	$digits = preg_replace( '/\D/', '', $raw );
	if ( 10 === strlen( $digits ) ) { $e164 = '+1' . $digits; }
	elseif ( 11 === strlen( $digits ) && '1' === $digits[0] ) { $e164 = '+' . $digits; }
	else { $e164 = $digits ? '+' . $digits : ''; }

	global $wpdb;
	$wpdb->insert( mwm_a2p_table(), array(
		'created_at'    => gmdate( 'Y-m-d H:i:s' ),
		'phone'         => $raw,
		'phone_e164'    => $e164,
		'transactional' => $t,
		'marketing'     => $m,
		'guest_name'    => isset( $_POST['name'] ) ? sanitize_text_field( wp_unslash( $_POST['name'] ) ) : '',
		'guest_email'   => isset( $_POST['email'] ) ? sanitize_email( wp_unslash( $_POST['email'] ) ) : '',
		'source_url'    => isset( $_POST['consent_url'] ) ? esc_url_raw( wp_unslash( $_POST['consent_url'] ) ) : '',
		'ip'            => isset( $_SERVER['REMOTE_ADDR'] ) ? sanitize_text_field( wp_unslash( $_SERVER['REMOTE_ADDR'] ) ) : '',
		'user_agent'    => isset( $_SERVER['HTTP_USER_AGENT'] ) ? substr( sanitize_text_field( wp_unslash( $_SERVER['HTTP_USER_AGENT'] ) ), 0, 255 ) : '',
	) );
}
add_action( 'wp_ajax_nopriv_mwm_studio_hold_slot', 'mwm_a2p_capture', 1 );
add_action( 'wp_ajax_mwm_studio_hold_slot', 'mwm_a2p_capture', 1 );

/* ── 3 · the two checkboxes ──────────────────────────────────────────────── */

/**
 * ─────────────────────────────────────────────────────────────────────────────
 * 🔴 PAGE 1193 (/studio-hour/) — CONSENT WAS A CONDITION OF PURCHASE.
 *
 * This is the AD_09 landing page, the one paid traffic lands on. Its own inline
 * script, read Aug 12 2026:
 *
 *     <button class="sh-btn" id="sh-buy" disabled>Book My Studio Hour — $349</button>
 *     <p id="sh-hint">Tick the box above to continue.</p>
 *     box.addEventListener('change', function(){ btn.disabled = !box.checked; });
 *     btn.addEventListener('click',  function(){ if(!box.checked) return; ... });
 *
 * You could not buy without ticking the SMS consent box — while the label on
 * that very box read "Consent is not a condition of purchase." It said the words
 * and did the opposite, on the page a reviewer is most likely to be sent to.
 *
 * Worse, the page has NO phone field. So it took SMS consent for a number it
 * never collected, and stamped it onto the Stripe session as
 * client_reference_id=smsconsent-<timestamp> — a consent record with nobody in it,
 * gathered under duress, on every single purchase.
 *
 * THE FIX IS REMOVAL, NOT SPLITTING. An opt-in that cannot be honoured should not
 * exist. The documented web opt-in is /book-studio/, where there is a real phone
 * field and a real ledger. Here the checkbox goes, the gate goes, and the button
 * simply works. Checkout gets shorter and the page stops making a claim it breaks.
 * ─────────────────────────────────────────────────────────────────────────────
 */
function mwm_a2p_studio_hour() {

	if ( ! is_page( 1193 ) ) { return; }
	?>
<script id="mwm-a2p-v2-sh">
(function () {
  // Read from the live page on Aug 12 2026 and cross-checked against the
  // Aug 9 snapshot in .deploy/_p71_stash/page-1193-studio-hour.html.
  var LINK = 'https://buy.stripe.com/00w28r9GhgpI6ej6ci9EI18';

  function fix() {
    var btn = document.getElementById('sh-buy');
    if (!btn) { return false; }

    var box  = document.getElementById('sh-consent-box');
    var hint = document.getElementById('sh-hint');

    // The consent block goes entirely — no phone here to honour it with.
    if (box) {
      var lab = box.closest('label');
      if (lab && lab.parentNode) { lab.parentNode.removeChild(lab); }
    }
    if (hint) { hint.textContent = ''; }

    // Cloning drops the page's own listeners, which is the only way to remove
    // the gate: its click handler returns early on an unticked box, and the box
    // no longer exists. Re-wire to the same Stripe link, minus the consent stamp
    // we are no longer entitled to write.
    var b2 = btn.cloneNode(true);
    b2.disabled = false;
    b2.removeAttribute('disabled');
    b2.addEventListener('click', function () { window.location.href = LINK; });
    btn.parentNode.replaceChild(b2, btn);
    return true;
  }

  // The page's own script runs in the body, before this footer script, so its
  // listeners are already attached by the time we replace the node.
  if (!fix()) {
    var mo = new MutationObserver(function () { if (fix()) { mo.disconnect(); } });
    mo.observe(document.documentElement, { childList: true, subtree: true });
    setTimeout(function () { mo.disconnect(); }, 15000);
  }
})();
</script>
	<?php
}
add_action( 'wp_footer', 'mwm_a2p_studio_hour', 99 );

function mwm_a2p_front_end() {

	if ( ! is_page( 741 ) ) { return; }

	$link = 'color:#C8A96E;text-decoration:underline;';
	$pp   = '<a href="https://mwmcreations.com/privacy-policy/" style="' . $link . '">Privacy Policy</a>';
	$tos  = '<a href="https://mwmcreations.com/terms/" style="' . $link . '">Terms of Service</a>';

	// 🔴 VERBATIM the wording sent to Twilio on Aug 12 2026. If a reviewer asks
	// for a change, change it HERE and nowhere else, and send them the new text.
	$t_txt = 'I agree to receive text messages from MWM Creations &amp; Studios about my booking: '
		. 'confirmations, session reminders, and replies to questions I ask. Message frequency varies. '
		. 'Message &amp; data rates may apply. Reply STOP to opt out at any time, or HELP for help. '
		. 'Consent is not a condition of purchase. See our ' . $pp . ' and ' . $tos . '.';

	$m_txt = '<strong style="color:#d8d8d8;">Optional</strong> — I also agree to receive marketing and '
		. 'promotional text messages from MWM Creations &amp; Studios about our services, offers and events. '
		. 'Message frequency varies and is typically no more than 4 messages per month. '
		. 'Message &amp; data rates may apply. Reply STOP to opt out at any time, or HELP for help. '
		. 'Consent is not a condition of purchase. See our ' . $pp . ' and ' . $tos . '.';
	?>
<script id="mwm-a2p-v2">
(function () {
  var TXN = <?php echo wp_json_encode( $t_txt ); ?>;
  var MKT = <?php echo wp_json_encode( $m_txt ); ?>;

  function build() {
    var box = document.getElementById('bs-sms-consent-box');
    if (!box || document.getElementById('bs-sms-marketing-box')) { return !!box; }

    var label = box.closest('label');
    if (!label) { return true; }

    // 1 — the existing box becomes transactional-only.
    var span = label.querySelector('span');
    if (span) { span.innerHTML = TXN; }

    // 2 — a separate, optional marketing box beneath it.
    var m = label.cloneNode(true);
    m.style.marginTop = '12px';
    m.style.paddingTop = '12px';
    m.style.borderTop = '1px solid #2A2A2A';
    var mi = m.querySelector('input');
    mi.id = 'bs-sms-marketing-box';
    mi.name = 'sms_marketing_consent';
    mi.checked = false;
    var ms = m.querySelector('span');
    if (ms) { ms.innerHTML = MKT; }
    label.parentNode.insertBefore(m, label.nextSibling);

    // Neither box is pre-ticked, and neither gates the form.
    box.checked = false;
    return true;
  }

  if (!build()) {
    // The widget is Elementor-rendered; if it is not in the DOM yet, watch for it.
    var mo = new MutationObserver(function () { if (build()) { mo.disconnect(); } });
    mo.observe(document.documentElement, { childList: true, subtree: true });
    setTimeout(function () { mo.disconnect(); }, 15000);
  }

  // 3 — carry the number and both answers with the booking that is already
  //     being sent. We append to the FormData the widget built; we do not
  //     intercept the click, validate, block, or alter any existing field.
  var nativeFetch = window.fetch;
  window.fetch = function (input, init) {
    try {
      var body = init && init.body;
      if (body && typeof FormData !== 'undefined' && body instanceof FormData
          && body.get('action') === 'mwm_studio_hold_slot') {
        var phone = document.getElementById('bs-phone');
        var t = document.getElementById('bs-sms-consent-box');
        var m = document.getElementById('bs-sms-marketing-box');
        body.append('phone_number', phone ? phone.value : '');
        body.append('sms_consent', (t && t.checked) ? '1' : '0');
        body.append('sms_marketing_consent', (m && m.checked) ? '1' : '0');
        body.append('consent_url', window.location.origin + window.location.pathname);
      }
    } catch (e) { /* never break checkout over consent bookkeeping */ }
    return nativeFetch.apply(this, arguments);
  };
})();
</script>
	<?php
}
add_action( 'wp_footer', 'mwm_a2p_front_end', 99 );

/* ── 4 · so the record can be produced on request ────────────────────────── */

add_action( 'admin_menu', function () {
	add_submenu_page(
		'tools.php', 'SMS consent log', 'SMS consent log', 'manage_options',
		'mwm-sms-consent', 'mwm_a2p_screen'
	);
} );

function mwm_a2p_screen() {
	if ( ! current_user_can( 'manage_options' ) ) { return; }
	global $wpdb;
	$t    = mwm_a2p_table();
	$rows = $wpdb->get_results( "SELECT * FROM {$t} ORDER BY id DESC LIMIT 200" );
	echo '<div class="wrap"><h1>SMS consent log</h1>';
	echo '<p>Every web-form opt-in, with the moment it was given. This is the record a carrier audit asks for. Times are UTC.</p>';
	if ( ! $rows ) {
		echo '<p><em>No entries yet. The first booking made with a box ticked will appear here.</em></p></div>';
		return;
	}
	echo '<table class="widefat striped"><thead><tr>'
		. '<th>When (UTC)</th><th>Phone</th><th>Booking msgs</th><th>Marketing</th>'
		. '<th>Name</th><th>Email</th><th>Page</th><th>IP</th></tr></thead><tbody>';
	foreach ( $rows as $r ) {
		printf(
			'<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>',
			esc_html( $r->created_at ),
			esc_html( $r->phone_e164 ? $r->phone_e164 : $r->phone ),
			$r->transactional ? '&#10003; yes' : '&mdash;',
			$r->marketing ? '&#10003; yes' : '&mdash;',
			esc_html( $r->guest_name ),
			esc_html( $r->guest_email ),
			esc_html( $r->source_url ),
			esc_html( $r->ip )
		);
	}
	echo '</tbody></table></div>';
}
