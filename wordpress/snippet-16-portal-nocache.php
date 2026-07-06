<?php
// Code Snippets plugin — Snippet ID 16 (ACTIVE) — snapshot Jul 6 2026
// Studio Portal — bypass page caches (S7 fix, DEV Jul 5 2026)
// The portal login nonce dies after 24h; cached copies of /studio-portal/
// served every visitor a fossilized nonce -> 403 'Security check failed'.
add_action( 'template_redirect', function () {
	if ( is_page( 1102 ) || ( isset( $_SERVER['REQUEST_URI'] ) && false !== strpos( $_SERVER['REQUEST_URI'], '/studio-portal' ) ) ) {
		if ( ! defined( 'DONOTCACHEPAGE' ) ) { define( 'DONOTCACHEPAGE', true ); }
		nocache_headers();
	}
}, 0 );
