<?php
/**
 * Homepage Template - Bent Tree Gardens West
 */
get_header();

$hero_title    = get_theme_mod( 'btg_hero_title', 'Welcome to Bent Tree Gardens West' );
$hero_subtitle = get_theme_mod( 'btg_hero_subtitle', 'A welcoming gated community in Boynton Beach, Florida' );
$hero_image    = get_theme_mod( 'btg_hero_image', '' );
$hero_video    = content_url( '/uploads/2026/06/btg-hero-video-small.mp4' );
$hero_poster   = content_url( '/uploads/2026/06/btg-hero-poster.jpg' );
?>

<!-- Hero Section -->
<section class="btg-hero">
    <!-- Video Background (hidden on mobile - poster shown instead) -->
    <video class="btg-hero-video"
           autoplay muted loop playsinline
           poster="<?php echo esc_url( $hero_poster ); ?>"
           preload="auto">
        <source src="<?php echo esc_url( $hero_video ); ?>" type="video/mp4">
    </video>
    <!-- Poster fallback for mobile / no-video -->
    <div class="btg-hero-poster" style="background-image:url(<?php echo esc_url( $hero_poster ); ?>);"></div>
    <!-- Green overlay for text readability -->
    <div class="btg-hero-overlay"></div>
    <div class="btg-container" style="position:relative;z-index:3;">
        <div class="btg-hero-content">
            <h1><?php echo esc_html( $hero_title ); ?></h1>
            <p><?php echo esc_html( $hero_subtitle ); ?></p>
            <a href="<?php echo esc_url( home_url( '/amenities/' ) ); ?>" class="btg-btn">Explore Amenities</a>
            <a href="<?php echo esc_url( home_url( '/contact/' ) ); ?>" class="btg-btn btg-btn-outline" style="margin-left:12px;">Contact Us</a>
        </div>
    </div>
</section>

<!-- Quick Info Cards -->
<section class="btg-section btg-section-alt">
    <div class="btg-container">
        <div class="btg-grid btg-grid-4">
            <div class="btg-card" style="text-align:center;padding:24px;">
                <div style="margin-bottom:8px;"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#2E7D32" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18"/><path d="M5 21V7l8-4v18"/><path d="M13 21V3l6 3v15"/><path d="M9 7v.01M9 11v.01M9 15v.01M17 8v.01M17 12v.01M17 16v.01"/></svg></div>
                <h3 style="font-size:1.1rem;">13 Buildings</h3>
                <p>Spacious condominiums across a beautifully maintained campus</p>
            </div>
            <div class="btg-card" style="text-align:center;padding:24px;">
                <div style="margin-bottom:8px;"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#2E7D32" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg></div>
                <h3 style="font-size:1.1rem;">265 Units</h3>
                <p>A close-knit community of homeowners and residents</p>
            </div>
            <div class="btg-card" style="text-align:center;padding:24px;">
                <div style="margin-bottom:8px;"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#2E7D32" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="10" r="3"/><path d="M12 21.7C17.3 17 20 13 20 10a8 8 0 1 0-16 0c0 3 2.7 7 8 11.7z"/></svg></div>
                <h3 style="font-size:1.1rem;">Boynton Beach, FL</h3>
                <p>A welcoming gated community in sunny Boynton Beach, FL</p>
            </div>
            <div class="btg-card" style="text-align:center;padding:24px;">
                <div style="margin-bottom:8px;"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#2E7D32" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/></svg></div>
                <h3 style="font-size:1.1rem;">Gated &amp; Secure</h3>
                <p>24/7 gated access for peace of mind</p>
            </div>
        </div>
    </div>
</section>

<!-- Amenities Photo Showcase -->
<section class="btg-section">
    <div class="btg-container">
        <div class="btg-section-title">
            <h2>Our Community</h2>
            <p>Resort-style amenities and beautifully maintained grounds</p>
        </div>
        <div class="btg-grid btg-grid-3">
            <div class="btg-card">
                <div class="btg-card-img" style="background-image:url(<?php echo content_url('/uploads/2026/06/BTG_POOL_001.jpg'); ?>);"></div>
                <div class="btg-card-body"><h3>Swimming Pool</h3><p>Heated community pool with lounging areas and shaded seating</p></div>
            </div>
            <div class="btg-card">
                <div class="btg-card-img" style="background-image:url(<?php echo content_url('/uploads/2026/06/BTG_CLUBHOUSE_002.jpg'); ?>);"></div>
                <div class="btg-card-body"><h3>Clubhouse</h3><p>Multi-purpose space for events, meetings, and social gatherings</p></div>
            </div>
            <div class="btg-card">
                <div class="btg-card-img" style="background-image:url(<?php echo content_url('/uploads/2026/06/BTG_GYM_001.jpg'); ?>);"></div>
                <div class="btg-card-body"><h3>Fitness Center</h3><p>Stay active with our well-equipped community gym</p></div>
            </div>
            <div class="btg-card">
                <div class="btg-card-img" style="background-image:url(<?php echo content_url('/uploads/2026/06/BTG_DRONE_006.jpg'); ?>);"></div>
                <div class="btg-card-body"><h3>13 Buildings</h3><p>Set across lush, tropical landscaped grounds</p></div>
            </div>
            <div class="btg-card">
                <div class="btg-card-img" style="background-image:url(<?php echo content_url('/uploads/2026/06/BTG_BARBECUE_AREA_006.jpg'); ?>);"></div>
                <div class="btg-card-body"><h3>BBQ &amp; Picnic Area</h3><p>Outdoor grills and covered picnic areas for gatherings</p></div>
            </div>
            <div class="btg-card">
                <div class="btg-card-img" style="background-image:url(<?php echo content_url('/uploads/2026/06/BTG_EXTERIOR_001.jpg'); ?>);"></div>
                <div class="btg-card-body"><h3>Beautiful Exteriors</h3><p>Well-maintained buildings with covered walkways and tropical landscaping</p></div>
            </div>
        </div>
        <div style="text-align:center;margin-top:24px;">
            <a href="<?php echo esc_url( home_url( '/gallery/' ) ); ?>" class="btg-btn btg-btn-green">View Photo Gallery</a>
            <a href="<?php echo esc_url( home_url( '/amenities/' ) ); ?>" class="btg-btn btg-btn-outline" style="margin-left:12px;border-color:var(--btg-green);color:var(--btg-green);">All Amenities</a>
        </div>
    </div>
</section>

<!-- Latest News -->
<section class="btg-section btg-section-alt">
    <div class="btg-container">
        <div class="btg-section-title">
            <h2>News &amp; Announcements</h2>
            <p>Stay informed about the latest community updates</p>
        </div>
        <?php echo do_shortcode( '[btg_latest_news limit="3"]' ); ?>
        <div style="text-align:center;margin-top:24px;">
            <a href="<?php echo esc_url( home_url( '/news/' ) ); ?>" class="btg-btn btg-btn-green">View All News</a>
        </div>
    </div>
</section>

<!-- Upcoming Events -->
<section class="btg-section btg-section-green">
    <div class="btg-container">
        <div class="btg-section-title">
            <h2>Upcoming Events</h2>
            <p>Community gatherings, board meetings, and activities</p>
        </div>
        <div style="max-width:700px;margin:0 auto;">
            <?php echo do_shortcode( '[btg_upcoming_events limit="5"]' ); ?>
        </div>
        <div style="text-align:center;margin-top:24px;">
            <a href="<?php echo esc_url( home_url( '/events/' ) ); ?>" class="btg-btn btg-btn-green">Full Calendar</a>
        </div>
    </div>
</section>

<!-- Board Members -->
<section class="btg-section btg-section-alt">
    <div class="btg-container">
        <div class="btg-section-title">
            <h2>Your Board of Directors</h2>
            <p>Meet the dedicated volunteers who serve our community</p>
        </div>
        <?php echo do_shortcode( '[btg_board_members]' ); ?>
    </div>
</section>

<!-- Contact CTA -->
<section class="btg-section" style="background:var(--btg-green-dark);color:#fff;text-align:center;">
    <div class="btg-container">
        <h2 style="color:#fff;font-size:2rem;margin-bottom:12px;">Questions? We're Here to Help.</h2>
        <p style="color:#A5D6A7;font-size:1.1rem;max-width:500px;margin:0 auto 24px;">
            Reach out to our management team or visit the office during business hours.
        </p>
        <a href="<?php echo esc_url( home_url( '/contact/' ) ); ?>" class="btg-btn" style="font-size:16px;padding:14px 36px;">Contact Us</a>
    </div>
</section>

<?php get_footer(); ?>