<?php
// Code Snippets plugin — Snippet 20 — "A2P 10DLC - marketing consent line on booking pages (741, 1193)"
// DEV · Aug 10 2026 · LIVE + ACTIVE · campaign CM87b39e12beba8e7816460e18178dae38
//
// WHY THIS IS A SNIPPET AND NOT A PAGE EDIT
// The consent checkbox on /book-studio/ (741) lives inside the SAME Elementor
// HTML widget as the ~14KB inline checkout script — the only revenue-taking
// checkout in the business. The repo copy is a RENDERED snapshot, documented
// as "the floor, not the finished job", so a rebuild is not byte-perfect.
// Retyping that widget to change one sentence risks losing checkout AND the
// AD_09 funnel (snippet 19 drives #bs-editing-checkbox and .bs-hour-card,
// which exist only inside it). This rewrites the RENDERED OUTPUT instead and
// never touches _elementor_data. Deactivating the snippet reverts it exactly.
//
// Twilio reviewer, Aug 10 2026: "The Opt-in language found in the link
// provided does not align with the Use Case provided (marketing consent is
// missing). ... (add marketing consent)"
//
// Verified live after activation: /book-studio/ and /studio-hour/ both render
// the new sentence; hour cards, editing toggle, price and Mobile Phone Number
// field all still present; no PHP notice.
//
// ⚠️ WP Fastest Cache serves /studio-hour/ from cache — after any change here,
//    Settings → WP Fastest Cache → Clear Cache → "Clear Cache and Minified".
//
// BELOW IS THE EXACT CODE AS ENTERED IN THE SNIPPET EDITOR (one line):

add_action('template_redirect', function(){ if(!is_page(array(741,1193))){ return; } ob_start(function($h){ $o=' about my inquiry and our services. Message frequency varies; message &amp; data rates may apply. Reply STOP to opt out, HELP for help.'; $n=', including booking confirmations, session reminders, and marketing and promotional messages about our services, offers and events. Message frequency varies and is typically no more than 4 messages per month. Message &amp; data rates may apply. Reply STOP to opt out at any time, or HELP for help.'; if(strpos($h,$o)===false){ return $h; } return str_replace($o,$n,$h); }); }, 0);
