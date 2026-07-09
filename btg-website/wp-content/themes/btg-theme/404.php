<?php
/**
 * 404 Page
 */
get_header();
?>

<section class="btg-section" style="text-align:center;min-height:50vh;display:flex;align-items:center;">
    <div class="btg-container">
        <div style="font-size:80px;margin-bottom:16px;">🌴</div>
        <h1 style="font-size:3rem;margin-bottom:12px;">Page Not Found</h1>
        <p style="color:var(--btg-text-light);font-size:1.1rem;max-width:400px;margin:0 auto 24px;">
            The page you're looking for doesn't exist or has been moved.
        </p>
        <a href="<?php echo esc_url( home_url( '/' ) ); ?>" class="btg-btn btg-btn-green">Back to Home</a>
    </div>
</section>

<?php get_footer(); ?>
