<?php
/**
 * Default template — Blog/Archive listing
 */
get_header();
?>

<section class="btg-section">
    <div class="btg-container">
        <?php if ( is_archive() ) : ?>
            <div class="btg-section-title">
                <h2><?php the_archive_title(); ?></h2>
            </div>
        <?php endif; ?>

        <?php if ( have_posts() ) : ?>
            <div class="btg-grid btg-grid-3">
                <?php while ( have_posts() ) : the_post(); ?>
                    <div class="btg-card">
                        <?php if ( has_post_thumbnail() ) : ?>
                            <div class="btg-card-img" style="background-image:url(<?php the_post_thumbnail_url( 'btg-card' ); ?>);"></div>
                        <?php endif; ?>
                        <div class="btg-card-body">
                            <h3><a href="<?php the_permalink(); ?>"><?php the_title(); ?></a></h3>
                            <p style="font-size:12px;color:var(--btg-text-light);margin-bottom:8px;">
                                <?php echo get_the_date(); ?>
                            </p>
                            <p><?php echo wp_trim_words( get_the_excerpt(), 25 ); ?></p>
                            <a href="<?php the_permalink(); ?>" class="btg-btn btg-btn-green" style="font-size:12px;padding:8px 16px;">
                                Read More
                            </a>
                        </div>
                    </div>
                <?php endwhile; ?>
            </div>

            <div style="text-align:center;margin-top:32px;">
                <?php
                the_posts_pagination( array(
                    'mid_size' => 2,
                    'prev_text' => '&laquo; Previous',
                    'next_text' => 'Next &raquo;',
                ) );
                ?>
            </div>
        <?php else : ?>
            <p style="text-align:center;color:var(--btg-text-light);">No posts found.</p>
        <?php endif; ?>
    </div>
</section>

<?php get_footer(); ?>
