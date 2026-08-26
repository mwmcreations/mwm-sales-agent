<?php
// Code Snippets plugin — Snippet ID 64 (ACTIVE) — DEV, Aug 26 2026
// ROADMAP Portal — bypass page caches.
//
// THE BUG: /roadmap-portal/ was served to anonymous visitors as a STATIC
// CACHED FILE. Cold fetches returned a page carrying a
// "WP Fastest Cache file was created ... 12:31 pm" footer. Because a
// successful login sets a cookie and REDIRECTS, the redirect landed back on
// the cached logged-out copy: the client saw the login form again, fields
// blank, NO error message. Which looks exactly like a wrong password.
//
// It never reproduced in wp-admin because WPFC does not serve cached pages to
// logged-in users, and both of us were signed in.
//
// Same failure and same fix as snippet 16 for /studio-portal/ (S7.3, July).
//
// 🔴 THE HALF THAT ACTUALLY COUNTS IS NOT HERE. WP Fastest Cache largely
// ignores DONOTCACHEPAGE. The fix that mattered is the WPFC rule
// Exclude > Exclude Pages > "Starts With: roadmap-portal", set in the plugin
// UI on 26 Aug alongside the existing studio-portal rule. This snippet covers
// every OTHER cache layer on the box and sends the no-store headers.
add_action( 'template_redirect', function () {
    $uri = isset( $_SERVER['REQUEST_URI'] ) ? $_SERVER['REQUEST_URI'] : '';
    if ( is_page( 1202 ) || ( $uri && false !== strpos( $uri, '/roadmap-portal' ) ) ) {
        if ( ! defined( 'DONOTCACHEPAGE' ) ) { define( 'DONOTCACHEPAGE', true ); }
        if ( ! defined( 'DONOTCACHEOBJECT' ) ) { define( 'DONOTCACHEOBJECT', true ); }
        if ( ! defined( 'DONOTCACHEDB' ) ) { define( 'DONOTCACHEDB', true ); }
        nocache_headers();
    }
}, 0 );
