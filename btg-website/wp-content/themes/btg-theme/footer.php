</main><!-- #main-content -->

<footer class="btg-footer">
    <div class="btg-container">
        <div class="btg-footer-grid">
            <!-- Column 1: About -->
            <div>
                <img src="<?php echo esc_url( get_template_directory_uri() . '/assets/images/logo.png' ); ?>"
                     alt="Bent Tree Gardens West"
                     class="btg-footer-logo">
                <p>
                    A welcoming gated community in Boynton Beach, Florida.
                    265 units across 13 buildings, offering a welcoming and well-managed
                    living environment for our residents.
                </p>
            </div>

            <!-- Column 2: Quick Links -->
            <div>
                <h4>Quick Links</h4>
                <?php
                wp_nav_menu( array(
                    'theme_location' => 'footer',
                    'container'      => false,
                    'menu_class'     => 'btg-footer-links',
                    'depth'          => 1,
                    'fallback_cb'    => function() {
                        echo '<ul class="btg-footer-links">';
                        echo '<li><a href="' . esc_url( home_url( '/documents/' ) ) . '">Document Library</a></li>';
                        echo '<li><a href="' . esc_url( home_url( '/board-members/' ) ) . '">Board Members</a></li>';
                        echo '<li><a href="' . esc_url( home_url( '/events/' ) ) . '">Community Calendar</a></li>';
                        echo '<li><a href="' . esc_url( home_url( '/contact/' ) ) . '">Contact Us</a></li>';
                        echo '<li><a href="' . esc_url( home_url( '/faq/' ) ) . '">FAQ</a></li>';
                        echo '</ul>';
                    },
                ) );
                ?>
            </div>

            <!-- Column 3: Contact -->
            <div>
                <h4>Contact Information</h4>
                <p>
                    <?php echo esc_html( btg_get_contact( 'btg_address' ) ?: '9990 Pineapple Tree Dr, Boynton Beach, FL 33436' ); ?><br><br>
                    Phone: <a href="tel:<?php echo esc_attr( preg_replace( '/[^0-9+]/', '', btg_get_contact( 'btg_phone' ) ?: '5613743360' ) ); ?>">
                        <?php echo esc_html( btg_get_contact( 'btg_phone' ) ?: '561-374-3360' ); ?>
                    </a><br>
                    <?php if ( btg_get_contact( 'btg_email' ) ) : ?>
                        Email: <a href="mailto:<?php echo esc_attr( btg_get_contact( 'btg_email' ) ); ?>">
                            <?php echo esc_html( btg_get_contact( 'btg_email' ) ); ?>
                        </a><br>
                    <?php endif; ?>
                    <br>
                    <?php echo esc_html( btg_get_contact( 'btg_office_hours' ) ?: 'Mon-Fri: 9:00 AM - 5:00 PM' ); ?>
                </p>
            </div>
        </div>

        <div class="btg-footer-bottom">
            <p>&copy; <?php echo date( 'Y' ); ?> Bent Tree Gardens West Condominium Association, Inc. All rights reserved.</p>
            <p class="mwm-credit">Website by <a href="https://mwmcreations.com" target="_blank" rel="noopener">MWM Creations & Studios</a></p>
        </div>
    </div>
</footer>

<?php wp_footer(); ?>
</body>
</html>
