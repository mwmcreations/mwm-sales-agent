<?php
/**
 * Template Name: Resident Portal
 * Secure area for logged-in homeowners/residents
 */
get_header();

if ( ! is_user_logged_in() ) :
?>
<section class="btg-section">
    <div class="btg-container" style="max-width:500px;text-align:center;">
        <h2>Resident Portal</h2>
        <p style="color:var(--btg-text-light);margin-bottom:24px;">
            Log in with your resident credentials to access your account, community documents, and services.
        </p>
        <?php
        wp_login_form( array(
            'redirect'       => get_permalink(),
            'label_username' => 'Email Address',
            'label_password' => 'Password',
        ) );
        ?>
        <p style="margin-top:16px;font-size:14px;color:var(--btg-text-light);">
            Forgot your password? <a href="<?php echo esc_url( wp_lostpassword_url( get_permalink() ) ); ?>">Reset it here</a>.
        </p>
        <div class="btg-notice btg-notice-info" style="margin-top:24px;">
            <strong>New resident?</strong> Contact the management office at
            <?php echo esc_html( btg_get_contact( 'btg_phone' ) ?: '561-374-3360' ); ?>
            to receive your login credentials.
        </div>
    </div>
</section>

<?php else :
    $current_user = wp_get_current_user();
    global $wpdb;
    $prefix = $wpdb->prefix . 'btg_';

    // Try to find resident record
    $resident = $wpdb->get_row( $wpdb->prepare(
        "SELECT r.*, u.unit_number, u.building_id, b.building_number
         FROM {$prefix}residents r
         LEFT JOIN {$prefix}units u ON r.unit_id = u.unit_id
         LEFT JOIN {$prefix}buildings b ON u.building_id = b.building_id
         WHERE r.email = %s AND r.is_active = 1
         LIMIT 1",
        $current_user->user_email
    ) );
?>

<section class="btg-section">
    <div class="btg-container">
        <div class="btg-section-title">
            <h2>Welcome, <?php echo esc_html( $current_user->display_name ); ?></h2>
            <?php if ( $resident ) : ?>
                <p>Building <?php echo esc_html( $resident->building_number ); ?>, Unit <?php echo esc_html( $resident->unit_number ); ?></p>
            <?php else : ?>
                <p>Your Resident Portal</p>
            <?php endif; ?>
        </div>

        <div class="btg-grid btg-grid-3">
            <!-- Documents -->
            <a href="<?php echo esc_url( home_url( '/documents/' ) ); ?>" class="btg-card" style="text-align:center;padding:32px 24px;text-decoration:none;color:inherit;">
                <div style="font-size:48px;margin-bottom:12px;">📂</div>
                <h3 style="font-size:1.1rem;margin-bottom:8px;">Documents</h3>
                <p>Access governing documents, financials, meeting minutes, and forms</p>
            </a>

            <!-- Community Calendar -->
            <a href="<?php echo esc_url( home_url( '/events/' ) ); ?>" class="btg-card" style="text-align:center;padding:32px 24px;text-decoration:none;color:inherit;">
                <div style="font-size:48px;margin-bottom:12px;">📅</div>
                <h3 style="font-size:1.1rem;margin-bottom:8px;">Calendar</h3>
                <p>View upcoming meetings, events, and community activities</p>
            </a>

            <!-- Contact Board -->
            <a href="<?php echo esc_url( home_url( '/contact/' ) ); ?>" class="btg-card" style="text-align:center;padding:32px 24px;text-decoration:none;color:inherit;">
                <div style="font-size:48px;margin-bottom:12px;">📬</div>
                <h3 style="font-size:1.1rem;margin-bottom:8px;">Contact</h3>
                <p>Submit maintenance requests or reach the management office</p>
            </a>

            <!-- Board Members -->
            <a href="<?php echo esc_url( home_url( '/board-members/' ) ); ?>" class="btg-card" style="text-align:center;padding:32px 24px;text-decoration:none;color:inherit;">
                <div style="font-size:48px;margin-bottom:12px;">👥</div>
                <h3 style="font-size:1.1rem;margin-bottom:8px;">Board of Directors</h3>
                <p>Meet your board members and committee chairs</p>
            </a>

            <!-- News -->
            <a href="<?php echo esc_url( home_url( '/news/' ) ); ?>" class="btg-card" style="text-align:center;padding:32px 24px;text-decoration:none;color:inherit;">
                <div style="font-size:48px;margin-bottom:12px;">📰</div>
                <h3 style="font-size:1.1rem;margin-bottom:8px;">News</h3>
                <p>Latest announcements and community updates</p>
            </a>

            <!-- Gallery -->
            <a href="<?php echo esc_url( home_url( '/gallery/' ) ); ?>" class="btg-card" style="text-align:center;padding:32px 24px;text-decoration:none;color:inherit;">
                <div style="font-size:48px;margin-bottom:12px;">📸</div>
                <h3 style="font-size:1.1rem;margin-bottom:8px;">Photo Gallery</h3>
                <p>Browse community photos and event albums</p>
            </a>
        </div>

        <!-- Quick Info -->
        <div class="btg-notice btg-notice-info" style="margin-top:32px;">
            <strong>Office Hours:</strong> <?php echo esc_html( btg_get_contact( 'btg_office_hours' ) ?: 'Mon-Fri: 9:00 AM - 5:00 PM' ); ?> &bull;
            <strong>Phone:</strong> <?php echo esc_html( btg_get_contact( 'btg_phone' ) ?: '561-374-3360' ); ?>
            <?php $emergency = btg_get_contact( 'btg_emergency_phone' ); if ( $emergency ) : ?>
                &bull; <strong>Emergency:</strong> <?php echo esc_html( $emergency ); ?>
            <?php endif; ?>
        </div>
    </div>
</section>

<?php endif; ?>

<?php get_footer(); ?>
