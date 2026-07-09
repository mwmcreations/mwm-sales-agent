<?php
/**
 * Single post/news template
 */
get_header();
?>

<section class="btg-section">
    <div class="btg-container" style="max-width:800px;">
        <?php while ( have_posts() ) : the_post(); ?>
            <article>
                <p style="font-size:13px;color:var(--btg-text-light);margin-bottom:8px;">
                    <?php echo get_the_date( 'F j, Y' ); ?>
                    <?php
                    $post_type = get_post_type();
                    if ( $post_type === 'btg_news' ) {
                        echo ' &bull; News & Announcements';
                    }
                    ?>
                </p>
                <h1 style="margin-bottom:24px;"><?php the_title(); ?></h1>

                <?php if ( has_post_thumbnail() ) : ?>
                    <div style="margin-bottom:24px;border-radius:var(--btg-radius-lg);overflow:hidden;">
                        <?php the_post_thumbnail( 'large' ); ?>
                    </div>
                <?php endif; ?>

                <div class="btg-page-content">
                    <?php the_content(); ?>
                </div>
            </article>

            <div style="margin-top:40px;padding-top:24px;border-top:1px solid var(--btg-gray-200);">
                <a href="<?php echo esc_url( get_post_type_archive_link( $post_type ?: 'post' ) ); ?>" class="btg-btn btg-btn-green" style="font-size:13px;">
                    &larr; Back to <?php echo $post_type === 'btg_news' ? 'News' : 'All Posts'; ?>
                </a>
            </div>
        <?php endwhile; ?>
    </div>
</section>

<?php get_footer(); ?>
