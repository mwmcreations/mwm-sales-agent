<?php
/**
 * Template Name: Amenities
 */
get_header();
$upload = content_url( '/uploads/2026/06/' );
?>

<!-- Hero Banner -->
<section class="btg-section" style="background:var(--btg-green-dark);color:#fff;text-align:center;padding:48px 0;">
    <div class="btg-container">
        <h1 style="color:#fff;font-size:2.2rem;margin-bottom:8px;">Community Amenities</h1>
        <p style="color:#A5D6A7;font-size:1.1rem;">Resort-style living at Bent Tree Gardens West</p>
    </div>
</section>

<!-- Swimming Pool -->
<section class="btg-section">
    <div class="btg-container">
        <div class="btg-amenity-row">
            <div class="btg-amenity-photos">
                <img src="<?php echo esc_url( $upload . 'BTG_POOL_001.jpg' ); ?>" alt="Bent Tree Gardens Pool">
                <div class="btg-amenity-photo-grid">
                    <img src="<?php echo esc_url( $upload . 'BTG_POOL_002.jpg' ); ?>" alt="Pool seating area">
                    <img src="<?php echo esc_url( $upload . 'BTG_POOL_004.jpg' ); ?>" alt="Pool lounge">
                </div>
            </div>
            <div class="btg-amenity-info">
                <h2>Swimming Pool</h2>
                <p>Our heated community pool is the centerpiece of outdoor living at Bent Tree Gardens West. Surrounded by comfortable lounging areas and shaded seating, it is the perfect spot to relax, socialize, or cool off on a sunny Florida day.</p>
                <ul class="btg-amenity-features">
                    <li>Heated community pool</li>
                    <li>Shaded seating and umbrella areas</li>
                    <li>Lounge chairs and tables</li>
                    <li>Open daily for residents</li>
                </ul>
            </div>
        </div>
    </div>
</section>

<!-- Clubhouse -->
<section class="btg-section btg-section-alt">
    <div class="btg-container">
        <div class="btg-amenity-row btg-amenity-reverse">
            <div class="btg-amenity-photos">
                <img src="<?php echo esc_url( $upload . 'BTG_CLUBHOUSE_002.jpg' ); ?>" alt="Bent Tree Gardens Clubhouse">
                <div class="btg-amenity-photo-grid">
                    <img src="<?php echo esc_url( $upload . 'BTG_CLUBHOUSE_013.jpg' ); ?>" alt="Clubhouse interior">
                    <img src="<?php echo esc_url( $upload . 'BTG_CLUBHOUSE_004.jpg' ); ?>" alt="Clubhouse meeting space">
                </div>
            </div>
            <div class="btg-amenity-info">
                <h2>Clubhouse</h2>
                <p>Our spacious clubhouse serves as the social hub of the community. Whether it is a board meeting, holiday celebration, or a casual get-together, the clubhouse provides a comfortable and welcoming space for residents.</p>
                <ul class="btg-amenity-features">
                    <li>Multi-purpose event space</li>
                    <li>Community meetings and gatherings</li>
                    <li>Kitchen facilities</li>
                    <li>Comfortable seating areas</li>
                </ul>
            </div>
        </div>
    </div>
</section>

<!-- Fitness Center -->
<section class="btg-section">
    <div class="btg-container">
        <div class="btg-amenity-row">
            <div class="btg-amenity-photos">
                <img src="<?php echo esc_url( $upload . 'BTG_GYM_001.jpg' ); ?>" alt="Bent Tree Gardens Fitness Center">
                <div class="btg-amenity-photo-grid">
                    <img src="<?php echo esc_url( $upload . 'BTG_GYM_007.jpg' ); ?>" alt="Gym equipment">
                    <img src="<?php echo esc_url( $upload . 'BTG_GYM_009.jpg' ); ?>" alt="Fitness room">
                </div>
            </div>
            <div class="btg-amenity-info">
                <h2>Fitness Center</h2>
                <p>Stay active without leaving the community. Our fitness center offers equipment for cardio and strength training, available to all residents throughout the day.</p>
                <ul class="btg-amenity-features">
                    <li>Cardio and strength equipment</li>
                    <li>Air-conditioned facility</li>
                    <li>Convenient hours for residents</li>
                </ul>
            </div>
        </div>
    </div>
</section>

<!-- BBQ and Picnic Area -->
<section class="btg-section btg-section-alt">
    <div class="btg-container">
        <div class="btg-amenity-row btg-amenity-reverse">
            <div class="btg-amenity-photos">
                <img src="<?php echo esc_url( $upload . 'BTG_BARBECUE_AREA_006.jpg' ); ?>" alt="Bent Tree Gardens BBQ Area">
            </div>
            <div class="btg-amenity-info">
                <h2>BBQ &amp; Picnic Area</h2>
                <p>Fire up the grill and enjoy the Florida weather in our dedicated barbecue and picnic area. Perfect for family cookouts, birthday parties, or a casual meal outdoors with neighbors.</p>
                <ul class="btg-amenity-features">
                    <li>Outdoor BBQ grills</li>
                    <li>Covered picnic tables</li>
                    <li>Shaded gathering space</li>
                </ul>
            </div>
        </div>
    </div>
</section>

<!-- Leasing Office -->
<section class="btg-section">
    <div class="btg-container">
        <div class="btg-amenity-row">
            <div class="btg-amenity-photos">
                <img src="<?php echo esc_url( $upload . 'BTG_LEASING_OFFICE_001.jpg' ); ?>" alt="Leasing Office">
                <div class="btg-amenity-photo-grid">
                    <img src="<?php echo esc_url( $upload . 'BTG_LEASING_OFFICE_002.jpg' ); ?>" alt="Office interior">
                    <img src="<?php echo esc_url( $upload . 'BTG_LEASING_OFFICE_003.jpg' ); ?>" alt="Office reception">
                </div>
            </div>
            <div class="btg-amenity-info">
                <h2>Leasing Office</h2>
                <p>Our on-site management office is here to assist residents with any questions, maintenance requests, or community inquiries. Stop by during business hours or reach out anytime.</p>
                <ul class="btg-amenity-features">
                    <li>On-site management team</li>
                    <li>Maintenance request handling</li>
                    <li>Community information center</li>
                </ul>
            </div>
        </div>
    </div>
</section>

<!-- Grounds and Exterior -->
<section class="btg-section btg-section-alt">
    <div class="btg-container">
        <div class="btg-section-title">
            <h2>Beautifully Maintained Grounds</h2>
            <p>Tropical landscaping and well-kept exteriors throughout the community</p>
        </div>
        <div class="btg-grid btg-grid-3">
            <div class="btg-card">
                <div class="btg-card-img" style="background-image:url(<?php echo esc_url( $upload . 'BTG_DRONE_001.jpg' ); ?>);"></div>
            </div>
            <div class="btg-card">
                <div class="btg-card-img" style="background-image:url(<?php echo esc_url( $upload . 'BTG_EXTERIOR_001.jpg' ); ?>);"></div>
            </div>
            <div class="btg-card">
                <div class="btg-card-img" style="background-image:url(<?php echo esc_url( $upload . 'BTG_EXTERIOR_005.jpg' ); ?>);"></div>
            </div>
        </div>
        <div style="text-align:center;margin-top:24px;">
            <a href="<?php echo esc_url( home_url( '/gallery/' ) ); ?>" class="btg-btn btg-btn-green">View Full Gallery</a>
        </div>
    </div>
</section>

<!-- Contact CTA -->
<section class="btg-section" style="background:var(--btg-green-dark);color:#fff;text-align:center;">
    <div class="btg-container">
        <h2 style="color:#fff;font-size:2rem;margin-bottom:12px;">Interested in Our Community?</h2>
        <p style="color:#A5D6A7;font-size:1.1rem;max-width:500px;margin:0 auto 24px;">
            Contact us to learn more about available units and community living.
        </p>
        <a href="<?php echo esc_url( home_url( '/contact/' ) ); ?>" class="btg-btn" style="font-size:16px;padding:14px 36px;">Contact Us</a>
    </div>
</section>

<?php get_footer(); ?>