// A2P 10DLC — STANDALONE OPT-IN FORM at /sms-signup/
// DEV · Aug 12 2026 · companion to "A2P 10DLC v2.1"
//
// ─────────────────────────────────────────────────────────────────────────────
// 🔴 REJECTION #5, and the reviewer was right.
//
//   "Opt-In Error: We are unable to submit the form as there is no submit
//    button is present. Action Required: Kindly provide the compliant opt in link."
//
// Verified on the live page today: on a COLD load of /book-studio/ there is no
// submit button anywhere in the DOM. #bs-rs-pay does not exist until the visitor
// picks a number of hours AND a date AND a time slot — only then does the widget
// build the reserve form. A reviewer opens the URL, sees a phone field and a
// consent checkbox, and has nothing to press. They cannot complete the opt-in,
// so they cannot verify it, so they reject it. Three separate reviewers have now
// said a version of this.
//
// 🔑 A checkout is not an opt-in form. /book-studio/ is a checkout: the consent
//    boxes live inside a purchase flow that only reveals its button once you are
//    buying something. That is fine for customers and useless for a reviewer.
//
// So this is a real opt-in form and nothing else: name, mobile, the same two
// consent checkboxes, and a submit button that is present from the first paint.
// No login, no query string, no purchase, nothing to configure before it works.
// It writes to the SAME ledger as the booking form, so there is one consent
// record for the business rather than two.
//
// This becomes the opt-in URL we give Twilio. /book-studio/ keeps its checkboxes
// and keeps recording consent — it simply stops being the thing a reviewer is
// asked to complete.
// ─────────────────────────────────────────────────────────────────────────────

if ( ! defined( 'ABSPATH' ) ) { exit; }

define( 'MWM_OPTIN_FORM_V', '1.1.0' );

function mwm_optin_table() {
	global $wpdb;
	return function_exists( 'mwm_a2p_table' ) ? mwm_a2p_table() : $wpdb->prefix . 'mwm_sms_consent';
}

/* ── the page ────────────────────────────────────────────────────────────── */

add_action( 'init', function () {

	if ( get_option( 'mwm_optin_form_page' ) === MWM_OPTIN_FORM_V ) { return; }

	$existing = get_page_by_path( 'sms-signup' );
	if ( $existing ) {
		wp_update_post( array( 'ID' => $existing->ID, 'post_content' => '[mwm_sms_optin]', 'post_status' => 'publish' ) );
		$id = $existing->ID;
	} else {
		$id = wp_insert_post( array(
			'post_title'   => 'Text Message Sign-Up',
			'post_name'    => 'sms-signup',
			'post_content' => '[mwm_sms_optin]',
			'post_status'  => 'publish',
			'post_type'    => 'page',
		) );
	}
	update_option( 'mwm_optin_form_page', MWM_OPTIN_FORM_V, false );
	update_option( 'mwm_optin_form_page_id', (int) $id, false );
}, 20 );

/* ── the handler ─────────────────────────────────────────────────────────── */
/**
 * Runs before render so a successful submission can redirect (POST/redirect/GET)
 * and a refresh cannot double-record a consent.
 */
add_action( 'template_redirect', function () {

	if ( empty( $_POST['mwm_optin_submit'] ) ) { return; }
	if ( ! isset( $_POST['mwm_optin_nonce'] ) || ! wp_verify_nonce( sanitize_text_field( wp_unslash( $_POST['mwm_optin_nonce'] ) ), 'mwm_optin' ) ) {
		return; // stale form; the page will simply re-render
	}

	$name  = isset( $_POST['mwm_name'] ) ? sanitize_text_field( wp_unslash( $_POST['mwm_name'] ) ) : '';
	$phone = isset( $_POST['mwm_phone'] ) ? sanitize_text_field( wp_unslash( $_POST['mwm_phone'] ) ) : '';
	$email = isset( $_POST['mwm_email'] ) ? sanitize_email( wp_unslash( $_POST['mwm_email'] ) ) : '';
	$t     = ! empty( $_POST['mwm_txn'] ) ? 1 : 0;
	$m     = ! empty( $_POST['mwm_mkt'] ) ? 1 : 0;

	$digits = preg_replace( '/\D/', '', $phone );

	// 🔴 NEITHER CHECKBOX MAY BE REQUIRED. Twilio (Salic Shabbir, Aug 12):
	//   "Both the transactional and marketing consent checkboxes must be optional.
	//    Users should be able to submit the form without selecting either checkbox…
	//    Please update your form so that users can submit even if neither consent
	//    box is checked."
	// So the ONLY validation is on the fields we need to identify the person. A
	// submission with nothing ticked is a valid submission that grants nothing —
	// it is answered, acknowledged, and no consent is written.
	$err = '';
	if ( '' === trim( $name ) )       { $err = 'name'; }
	elseif ( strlen( $digits ) < 10 ) { $err = 'phone'; }

	if ( $err ) {
		wp_safe_redirect( add_query_arg( 'e', $err, get_permalink() ) );
		exit;
	}

	if ( ! $t && ! $m ) {
		// Submitted with neither box ticked. Nothing is written to the consent
		// ledger, because no consent was given — a ledger of non-consents is not
		// a consent record. The visitor is told plainly that we will not text them.
		wp_safe_redirect( add_query_arg( array( 'ok' => '1', 'none' => '1' ), get_permalink() ) );
		exit;
	}

	if ( 10 === strlen( $digits ) )                                  { $e164 = '+1' . $digits; }
	elseif ( 11 === strlen( $digits ) && '1' === $digits[0] )        { $e164 = '+' . $digits; }
	else                                                             { $e164 = '+' . $digits; }

	global $wpdb;
	$wpdb->insert( mwm_optin_table(), array(
		'created_at'    => gmdate( 'Y-m-d H:i:s' ),
		'phone'         => $phone,
		'phone_e164'    => $e164,
		'transactional' => $t,
		'marketing'     => $m,
		'guest_name'    => $name,
		'guest_email'   => $email,
		'source_url'    => home_url( '/sms-signup/' ),
		'ip'            => isset( $_SERVER['REMOTE_ADDR'] ) ? sanitize_text_field( wp_unslash( $_SERVER['REMOTE_ADDR'] ) ) : '',
		'user_agent'    => isset( $_SERVER['HTTP_USER_AGENT'] ) ? substr( sanitize_text_field( wp_unslash( $_SERVER['HTTP_USER_AGENT'] ) ), 0, 255 ) : '',
	) );

	wp_safe_redirect( add_query_arg( 'ok', '1', get_permalink() ) );
	exit;
} );

/* ── the form ────────────────────────────────────────────────────────────── */

add_shortcode( 'mwm_sms_optin', function () {

	$gold = '#C8A96E';
	$link = 'color:' . $gold . ';text-decoration:underline;';
	$pp   = '<a href="' . esc_url( home_url( '/privacy-policy/' ) ) . '" style="' . $link . '">Privacy Policy</a>';
	$tos  = '<a href="' . esc_url( home_url( '/terms/' ) ) . '" style="' . $link . '">Terms of Service</a>';

	$ok   = ! empty( $_GET['ok'] );
	$none = ! empty( $_GET['none'] );
	$e   = isset( $_GET['e'] ) ? sanitize_text_field( wp_unslash( $_GET['e'] ) ) : '';

	// 🔴 Word for word the same two consents as /book-studio/ and /sms-opt-in/.
	// If a reviewer ever asks for different wording it changes in all three or
	// none — three versions of the consent text is how this took five rounds.
	$t_txt = 'I agree to receive text messages from MWM Creations &amp; Studios about my booking: '
		. 'confirmations, session reminders, and replies to questions I ask. Message frequency varies. '
		. 'Message &amp; data rates may apply. Reply STOP to opt out at any time, or HELP for help. '
		. 'Consent is not a condition of purchase. See our ' . $pp . ' and ' . $tos . '.';

	$m_txt = '<strong>Optional</strong> &mdash; I also agree to receive marketing and promotional text '
		. 'messages from MWM Creations &amp; Studios about our services, offers and events. Message frequency '
		. 'varies and is typically no more than 4 messages per month. Message &amp; data rates may apply. '
		. 'Reply STOP to opt out at any time, or HELP for help. Consent is not a condition of purchase. '
		. 'See our ' . $pp . ' and ' . $tos . '.';

	$msg = '';
	if ( 'name' === $e )         { $msg = 'Please enter your name.'; }
	elseif ( 'phone' === $e )    { $msg = 'Please enter a valid mobile number.'; }

	ob_start();
	?>
<div style="max-width:600px;margin:40px auto;padding:0 20px;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;line-height:1.6;">

	<?php if ( $ok && $none ) : ?>
		<div style="border:1px solid #ccc;border-radius:10px;padding:24px;background:#fafafa;">
			<h2 style="margin-top:0;">Thanks &mdash; nothing has been signed up.</h2>
			<p>You submitted the form without ticking either box, which is completely fine. <strong>We will not send you any text messages.</strong> No consent has been recorded.</p>
			<p style="font-size:13px;color:#666;">If you meant to sign up, <a href="<?php echo esc_url( get_permalink() ); ?>" style="<?php echo esc_attr( $link ); ?>">go back and tick whichever box you want</a>.</p>
		</div>
	<?php elseif ( $ok ) : ?>
		<div style="border:1px solid <?php echo esc_attr( $gold ); ?>;border-radius:10px;padding:24px;background:#faf7f0;">
			<h2 style="margin-top:0;">You're signed up.</h2>
			<p>Thank you. We have recorded your preferences against your mobile number, with the date and time.</p>
			<p>You can stop at any time by replying <strong>STOP</strong> to any message, or reply <strong>HELP</strong> if you need us.</p>
			<p style="font-size:13px;color:#666;">Changed your mind about what you ticked? <a href="<?php echo esc_url( get_permalink() ); ?>" style="<?php echo esc_attr( $link ); ?>">Submit the form again</a> and the newer answer applies.</p>
		</div>
	<?php else : ?>

		<h1 style="font-size:26px;margin-bottom:6px;">Text message sign-up</h1>
		<p style="margin-top:0;color:#555;">MWM Creations &amp; Studios &mdash; 1500 Park Center Dr, Suite 230, Orlando, FL 32835</p>
		<p>Use this form to tell us which text messages you would like to receive from us. You can choose one, both, or neither &mdash; and you can change your mind at any time.</p>

		<?php if ( $msg ) : ?>
			<p style="border-left:4px solid #b32d2e;background:#fdf1f1;padding:10px 14px;margin:18px 0;"><strong><?php echo esc_html( $msg ); ?></strong></p>
		<?php endif; ?>

		<form method="post" action="<?php echo esc_url( get_permalink() ); ?>" style="margin-top:24px;">
			<?php wp_nonce_field( 'mwm_optin', 'mwm_optin_nonce' ); ?>

			<p style="margin-bottom:18px;">
				<label for="mwm_name" style="display:block;font-weight:600;margin-bottom:6px;">Your name</label>
				<input type="text" id="mwm_name" name="mwm_name" required autocomplete="name"
					style="width:100%;padding:12px 14px;border:1px solid #bbb;border-radius:8px;font-size:16px;box-sizing:border-box;">
			</p>

			<p style="margin-bottom:18px;">
				<label for="mwm_phone" style="display:block;font-weight:600;margin-bottom:6px;">Mobile phone number</label>
				<input type="tel" id="mwm_phone" name="mwm_phone" required autocomplete="tel" placeholder="(555) 123-4567"
					style="width:100%;padding:12px 14px;border:1px solid #bbb;border-radius:8px;font-size:16px;box-sizing:border-box;">
			</p>

			<p style="margin-bottom:24px;">
				<label for="mwm_email" style="display:block;font-weight:600;margin-bottom:6px;">Email <span style="font-weight:400;color:#777;">(optional)</span></label>
				<input type="email" id="mwm_email" name="mwm_email" autocomplete="email"
					style="width:100%;padding:12px 14px;border:1px solid #bbb;border-radius:8px;font-size:16px;box-sizing:border-box;">
			</p>

			<div style="border:1px solid #ddd;border-radius:10px;padding:16px;background:#fafafa;">
				<label style="display:flex;align-items:flex-start;gap:10px;cursor:pointer;font-size:14px;">
					<input type="checkbox" id="mwm_txn" name="mwm_txn" value="1" style="margin-top:4px;width:18px;height:18px;flex:none;">
					<span><?php echo wp_kses_post( $t_txt ); ?></span>
				</label>

				<label style="display:flex;align-items:flex-start;gap:10px;cursor:pointer;font-size:14px;margin-top:14px;padding-top:14px;border-top:1px solid #e3e3e3;">
					<input type="checkbox" id="mwm_mkt" name="mwm_mkt" value="1" style="margin-top:4px;width:18px;height:18px;flex:none;">
					<span><?php echo wp_kses_post( $m_txt ); ?></span>
				</label>
			</div>

			<p style="font-size:13px;color:#666;margin-top:12px;"><strong>Both boxes are optional.</strong> Neither is ticked for you, ticking the first does not sign you up for the second, and you can submit this form with neither ticked &mdash; in which case we will not text you at all.</p>

			<p style="margin-top:24px;">
				<button type="submit" id="mwm_optin_submit" name="mwm_optin_submit" value="1"
					style="background:<?php echo esc_attr( $gold ); ?>;color:#111;border:0;border-radius:8px;padding:15px 34px;font-size:17px;font-weight:700;cursor:pointer;">
					Submit
				</button>
			</p>
		</form>

		<p style="font-size:13px;color:#666;margin-top:28px;">
			How we handle consent, in full: <a href="<?php echo esc_url( home_url( '/sms-opt-in/' ) ); ?>" style="<?php echo esc_attr( $link ); ?>">SMS Opt-In Consent Documentation</a>.
			Questions: info@mwmcreations.com
		</p>

	<?php endif; ?>
</div>
	<?php
	return ob_get_clean();
} );
