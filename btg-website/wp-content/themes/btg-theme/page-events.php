<?php get_header(); ?>

<!-- Hero Banner -->
<section class="page-hero" style="background-image: url('<?php echo esc_url( get_site_url() ); ?>/wp-content/uploads/2026/06/BTG_CLUBHOUSE_013.jpg');">
    <div class="page-hero-content">
        <h1>Community Calendar</h1>
        <p>Stay connected with events, meetings, and activities happening in our community</p>
        <div class="page-hero-breadcrumb">
            <a href="<?php echo home_url(); ?>">Home</a> &mdash; Calendar
        </div>
    </div>
</section>

<!-- Events Listing -->
<section class="btg-section">
    <div class="btg-container">
        <div class="events-intro">
            <h2>Upcoming Events</h2>
            <p>From board meetings to social gatherings, there&rsquo;s always something happening at Bent Tree Gardens West. Check back often for the latest schedule.</p>
        </div>

        <div class="events-grid">
            <?php
            $events = new WP_Query( array(
                'post_type'      => 'btg_event',
                'posts_per_page' => 12,
                'orderby'        => 'meta_value',
                'meta_key'       => '_btg_event_date',
                'order'          => 'ASC',
                'meta_query'     => array(
                    array(
                        'key'     => '_btg_event_date',
                        'value'   => date( 'Y-m-d' ),
                        'compare' => '>=',
                        'type'    => 'DATE',
                    ),
                ),
            ) );

            if ( $events->have_posts() ) :
                while ( $events->have_posts() ) : $events->the_post();
                    $event_date     = get_post_meta( get_the_ID(), '_btg_event_date', true );
                    $event_time     = get_post_meta( get_the_ID(), '_btg_event_time', true );
                    $event_location = get_post_meta( get_the_ID(), '_btg_event_location', true );

                    $month = $event_date ? date( 'M', strtotime( $event_date ) ) : '';
                    $day   = $event_date ? date( 'j', strtotime( $event_date ) ) : '';
            ?>
                <div class="event-card">
                    <div class="event-card-date">
                        <span class="event-month"><?php echo esc_html( $month ); ?></span>
                        <span class="event-day"><?php echo esc_html( $day ); ?></span>
                    </div>
                    <div class="event-card-info">
                        <h3><?php the_title(); ?></h3>
                        <?php if ( $event_time ) : ?>
                            <div class="event-time"><?php echo esc_html( $event_time ); ?></div>
                        <?php endif; ?>
                        <?php if ( $event_location ) : ?>
                            <div class="event-location"><?php echo esc_html( $event_location ); ?></div>
                        <?php endif; ?>
                        <?php if ( get_the_excerpt() ) : ?>
                            <p><?php echo wp_trim_words( get_the_excerpt(), 20 ); ?></p>
                        <?php endif; ?>
                    </div>
                </div>
            <?php
                endwhile;
                wp_reset_postdata();
            else :
            ?>
                <div class="no-events-message">
                    <p>No upcoming events at this time. Check back soon for community activities and meetings!</p>
                </div>
            <?php endif; ?>
        </div>
    </div>
</section>

<!-- Community Venues -->
<section class="btg-section btg-section-alt">
    <div class="btg-container">
        <h2 class="btg-section-title">Our Event Venues</h2>
        <p style="text-align: center; color: var(--btg-text-light); max-width: 600px; margin: -10px auto 32px; font-size: 1.05rem;">Our community spaces are perfect for gatherings, celebrations, and social events of all kinds.</p>
        <div class="events-venue-strip">
            <div class="venue-photo">
                <img src="<?php echo esc_url( get_site_url() ); ?>/wp-content/uploads/2026/06/BTG_CLUBHOUSE_004.jpg" alt="Clubhouse event space" loading="lazy">
                <div class="venue-label">Clubhouse</div>
            </div>
            <div class="venue-photo">
                <img src="<?php echo esc_url( get_site_url() ); ?>/wp-content/uploads/2026/06/BTG_BARBECUE_AREA_006.jpg" alt="BBQ and outdoor area" loading="lazy">
                <div class="venue-label">BBQ Area</div>
            </div>
            <div class="venue-photo">
                <img src="<?php echo esc_url( get_site_url() ); ?>/wp-content/uploads/2026/06/BTG_POOL_004.jpg" alt="Pool area for events" loading="lazy">
                <div class="venue-label">Pool Deck</div>
            </div>
        </div>
    </div>
</section>

<!-- CTA -->
<section class="btg-cta-section" style="background-image: url('<?php echo esc_url( get_site_url() ); ?>/wp-content/uploads/2026/06/BTG_CLUBHOUSE_017.jpg');">
    <div class="btg-container">
        <h2>Want to Host a Community Event?</h2>
        <p>Contact the management office to learn about reserving our community spaces for your next event or gathering.</p>
        <a href="<?php echo home_url( '/contact/' ); ?>" class="btg-btn">Contact Management</a>
    </div>
</section>

<?php get_footer(); ?>
