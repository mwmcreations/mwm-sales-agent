<?php
/**
 * Snippet 17 — AD_09 deep-link preselect for /book-studio/
 *
 * WHY THIS EXISTS
 * AD_09 (Meta click-to-message) sells "one hour, filmed and edited, $349".
 * Before this snippet, a lead landing on /book-studio/ had to perform THREE
 * configuration steps to reach that price: pick 1 hour, flip the editing
 * toggle, then pick a date. Every step is a place to leave, on cold traffic,
 * from a 42-second ad that promised one simple thing.
 *
 * This makes the page accept URL parameters so MAYA / ERIC can send ONE link
 * that lands the lead directly on the $349 configuration with the calendar
 * already open:
 *
 *     https://mwmcreations.com/book-studio/?hours=1&editing=1
 *
 * WHY A SNIPPET AND NOT AN EDIT TO THE WIDGET
 * The booking widget is a ~14KB inline <script> inside an Elementor HTML
 * widget on page 741. It is NOT in the plugin and NOT in version control.
 * Editing it means hand-editing JSON in _elementor_data. This snippet is
 * purely additive, touches nothing existing, is reversible by deactivating
 * it, and lives in the repo.
 *
 * HOW IT WORKS
 * It does not reach into the widget's private state. It drives the widget's
 * OWN public controls — clicking the hour card and dispatching a real change
 * event on the checkbox — so every downstream handler (update, loadPicker,
 * calRefresh) runs exactly as it does for a human. No duplicated pricing
 * logic. Server-side pricing is unaffected and remains canonical.
 *
 * SAFETY
 * - No parameters present  -> does nothing at all, page behaves as before.
 * - hours outside 1..5     -> ignored.
 * - Widget not on the page -> gives up silently after ~4s of polling.
 * - Card already active    -> not clicked (the widget's handler TOGGLES, so a
 *                             blind second click would DESELECT it).
 *
 * LIVE: Code Snippets ID 19, "AD_09 Deep-Link — /book-studio/ hours + editing
 * preselect", scope Run everywhere, priority 10, ACTIVE since Aug 8 2026.
 * NOTE: in the Code Snippets editor the leading <?php is supplied by the
 * plugin and is NOT part of the snippet body.
 *
 * Author: DEV · Aug 8 2026 · mirrored to repo per wordpress/README.md
 */

add_action( 'wp_footer', function () {

	// Book Studio page only. 741 is the page ID; slug check is the fallback
	// so this survives a page-ID change.
	if ( ! is_page( 741 ) && ! is_page( 'book-studio' ) ) {
		return;
	}
	?>
	<script id="mwm-ad09-deeplink">
	(function () {
		var qs = new URLSearchParams( window.location.search );
		var rawEditing = ( qs.get( 'editing' ) || '' ).toLowerCase();
		var wantEditing = ( rawEditing === '1' || rawEditing === 'true' || rawEditing === 'yes' );
		var wantHours = parseInt( qs.get( 'hours' ), 10 );
		var validHours = ( wantHours >= 1 && wantHours <= 5 );

		// Nothing asked for -> do not touch the page.
		if ( ! wantEditing && ! validHours ) { return; }

		var tries = 0;

		function apply() {
			var cards = document.querySelectorAll( '.bs-hour-card' );
			var box   = document.getElementById( 'bs-editing-checkbox' );

			// Widget renders after Elementor; poll up to ~4s then give up.
			if ( ( ! cards.length || ! box ) && tries++ < 40 ) {
				return window.setTimeout( apply, 100 );
			}
			if ( ! cards.length || ! box ) { return; }

			// Editing FIRST, so the price tier is already correct when the
			// hour-card click triggers the widget's update().
			if ( wantEditing && ! box.checked ) {
				box.checked = true;
				box.dispatchEvent( new Event( 'change', { bubbles: true } ) );
			}

			if ( validHours ) {
				Array.prototype.forEach.call( cards, function ( card ) {
					var h = parseInt( card.getAttribute( 'data-hours' ), 10 );
					// Guard: the widget's own click handler toggles. Clicking an
					// already-active card would deselect it.
					if ( h === wantHours && ! card.classList.contains( 'bs-active' ) ) {
						card.click();
					}
				} );
			}
		}

		if ( document.readyState === 'loading' ) {
			document.addEventListener( 'DOMContentLoaded', apply );
		} else {
			apply();
		}
	})();
	</script>
	<?php
}, 99 );
