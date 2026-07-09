<!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
    <meta charset="<?php bloginfo( 'charset' ); ?>">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="Bent Tree Gardens West - Official website of the Bent Tree Gardens West Condominium Association in Boynton Beach, FL. 265 units, 13 buildings, gated community.">
    <?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>

<!-- Top Bar -->
<div class="btg-header-top">
    <div class="btg-container">
        <span><?php echo esc_html( btg_get_contact( 'btg_phone' ) ?: '561-374-3360' ); ?> &bull; <?php echo esc_html( btg_get_contact( 'btg_office_hours' ) ?: 'Mon-Fri: 9:00 AM - 5:00 PM' ); ?></span>
        <span>
            <?php if ( is_user_logged_in() ) : ?>
                <a href="<?php echo esc_url( wp_logout_url( home_url() ) ); ?>">Log Out</a>
            <?php else : ?>
                <a href="<?php echo esc_url( wp_login_url( home_url( '/resident-portal/' ) ) ); ?>">Login</a>
            <?php endif; ?>
        </span>
    </div>
</div>

<!-- Main Header with Integrated Nav -->
<header class="btg-header btg-header--integrated">
    <div class="btg-header-main">
        <div class="btg-container btg-header-integrated-inner">
            <!-- Logo + Site Name -->
            <div class="btg-header-brand">
                <a href="<?php echo esc_url( home_url( '/' ) ); ?>" class="btg-logo-link">
                    <?php if ( has_custom_logo() ) : ?>
                        <?php the_custom_logo(); ?>
                    <?php else : ?>
                        <img src="<?php echo esc_url( get_template_directory_uri() . '/assets/images/logo.png' ); ?>"
                            alt="Bent Tree Gardens West Condominium Association"
                            class="btg-logo-img btg-logo-img--nav">
                    <?php endif; ?>
                    <span class="btg-site-name">Bent Tree Gardens<br><small>West</small></span>
                </a>
            </div>

            <!-- Navigation -->
            <nav class="btg-nav btg-nav--integrated" role="navigation" aria-label="Primary Navigation">
                <div class="btg-container">
                    <button class="btg-nav-toggle" aria-label="Toggle navigation" onclick="document.querySelector('.btg-nav ul').classList.toggle('active')">
                        &#9776; Menu
                    </button>
                    <?php
                    wp_nav_menu( array(
                        'theme_location' => 'primary',
                        'container'      => false,
                        'menu_class'     => 'btg-nav-menu',
                        'fallback_cb'    => false,
                    ) );
                    ?>
                </div>
            </nav>
        </div>
    </div>
</header>
