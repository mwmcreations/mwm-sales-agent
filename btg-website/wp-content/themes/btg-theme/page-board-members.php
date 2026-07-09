<?php get_header(); ?>

<!-- Hero Banner -->
<section class="page-hero" style="background-image: url('<?php echo esc_url( get_site_url() ); ?>/wp-content/uploads/2026/06/BTG_CLUBHOUSE_009.jpg');">
    <div class="page-hero-content">
        <h1>Board of Directors</h1>
        <p>Meet the dedicated volunteers who lead and serve our community</p>
        <div class="page-hero-breadcrumb">
            <a href="<?php echo home_url(); ?>">Home</a> &mdash; Board
        </div>
    </div>
</section>

<!-- Board Introduction -->
<section class="btg-section">
    <div class="btg-container">
        <div class="board-intro">
            <h2>Community Leadership</h2>
            <p>Our Board of Directors is composed of dedicated resident volunteers who work tirelessly to maintain and improve Bent Tree Gardens West. They oversee community operations, finances, and long-term planning to ensure our community remains a wonderful place to call home.</p>
        </div>

        <!-- Dynamic Board Members from CPT -->
        <div class="board-members-grid">
            <?php
            $board_members = new WP_Query( array(
                'post_type'      => 'btg_board_member',
                'posts_per_page' => 12,
                'orderby'        => 'menu_order',
                'order'          => 'ASC',
            ) );

            if ( $board_members->have_posts() ) :
                while ( $board_members->have_posts() ) : $board_members->the_post();
                    $role     = get_post_meta( get_the_ID(), '_btg_member_role', true );
                    $building = get_post_meta( get_the_ID(), '_btg_member_building', true );
                    $bio      = get_the_excerpt();
                    $name     = get_the_title();
                    $initial  = mb_substr( $name, 0, 1 );
            ?>
                <div class="board-member-card">
                    <div class="board-member-photo">
                        <?php if ( has_post_thumbnail() ) : ?>
                            <?php the_post_thumbnail( 'medium', array( 'style' => 'width:100%;height:200px;object-fit:cover;' ) ); ?>
                        <?php else : ?>
                            <div class="member-avatar"><?php echo esc_html( $initial ); ?></div>
                        <?php endif; ?>
                    </div>
                    <div class="board-member-info">
                        <h3><?php the_title(); ?></h3>
                        <?php if ( $role ) : ?>
                            <div class="member-role"><?php echo esc_html( $role ); ?></div>
                        <?php endif; ?>
                        <?php if ( $building ) : ?>
                            <div class="member-building">Building <?php echo esc_html( $building ); ?></div>
                        <?php endif; ?>
                        <?php if ( $bio ) : ?>
                            <p><?php echo wp_trim_words( $bio, 25 ); ?></p>
                        <?php endif; ?>
                    </div>
                </div>
            <?php
                endwhile;
                wp_reset_postdata();
            else :
            ?>
                <!-- Placeholder cards when no board members are entered yet -->
                <div class="board-member-card">
                    <div class="board-member-photo">
                        <div class="member-avatar">P</div>
                    </div>
                    <div class="board-member-info">
                        <h3>President</h3>
                        <div class="member-role">Board President</div>
                        <p>Board member information coming soon. Our President leads the board and oversees all community operations.</p>
                    </div>
                </div>
                <div class="board-member-card">
                    <div class="board-member-photo">
                        <div class="member-avatar">VP</div>
                    </div>
                    <div class="board-member-info">
                        <h3>Vice President</h3>
                        <div class="member-role">Board Vice President</div>
                        <p>Board member information coming soon. The Vice President supports the President and steps in when needed.</p>
                    </div>
                </div>
                <div class="board-member-card">
                    <div class="board-member-photo">
                        <div class="member-avatar">T</div>
                    </div>
                    <div class="board-member-info">
                        <h3>Treasurer</h3>
                        <div class="member-role">Board Treasurer</div>
                        <p>Board member information coming soon. The Treasurer manages the community&rsquo;s financial operations and reporting.</p>
                    </div>
                </div>
                <div class="board-member-card">
                    <div class="board-member-photo">
                        <div class="member-avatar">S</div>
                    </div>
                    <div class="board-member-info">
                        <h3>Secretary</h3>
                        <div class="member-role">Board Secretary</div>
                        <p>Board member information coming soon. The Secretary handles meeting minutes and official records.</p>
                    </div>
                </div>
                <div class="board-member-card">
                    <div class="board-member-photo">
                        <div class="member-avatar">D</div>
                    </div>
                    <div class="board-member-info">
                        <h3>Director</h3>
                        <div class="member-role">Board Director</div>
                        <p>Board member information coming soon. Directors contribute to community decisions and committee work.</p>
                    </div>
                </div>
            <?php endif; ?>
        </div>
    </div>
</section>

<!-- Community Overview Photo -->
<section class="btg-section btg-section-alt">
    <div class="btg-container">
        <div style="border-radius: var(--btg-radius-lg); overflow: hidden; box-shadow: var(--btg-shadow-md);">
            <img src="<?php echo esc_url( get_site_url() ); ?>/wp-content/uploads/2026/06/BTG_DRONE_007.jpg" alt="Aerial view of Bent Tree Gardens West community" style="width: 100%; height: 300px; object-fit: cover; display: block;" loading="lazy">
        </div>
    </div>
</section>

<!-- Get Involved CTA -->
<section class="btg-section">
    <div class="btg-container">
        <div class="board-cta-box">
            <h3>Interested in Serving on the Board?</h3>
            <p>Our community thrives because of resident involvement. If you&rsquo;re interested in serving on the Board of Directors or joining a committee, we&rsquo;d love to hear from you.</p>
            <a href="<?php echo home_url( '/contact/' ); ?>" class="btg-btn btg-btn-green">Get Involved</a>
        </div>
    </div>
</section>

<?php get_footer(); ?>
