<?php
/**
 * Default page template
 */
get_header();
?>

<section class="btg-section">
    <div class="btg-container" style="max-width:800px;">
        <?php while ( have_posts() ) : the_post(); ?>
            <h1 style="margin-bottom:24px;"><?php the_title(); ?></h1>
            <div class="btg-page-content">
                <?php the_content(); ?>
            </div>
        <?php endwhile; ?>
    </div>
</section>

<?php get_footer(); ?>
