<?php
/**
 * Plugin Name: BTG Admin Dashboard
 * Plugin URI:  https://mwmcreations.com
 * Description: Custom admin dashboard for Bent Tree Gardens West HOA — manages owners, renters, parking permits, meetings, board members, documents, and email blasts.
 * Version:     1.2.0
 * Author:      MWM Creations & Studios
 * Author URI:  https://mwmcreations.com
 * License:     Proprietary
 * Text Domain: btg-admin
 *
 * Built for: Bent Tree Gardens West Condominium Association, Inc.
 *            9990 Pineapple Tree Dr, Boynton Beach, FL 33436
 *            265 units · 13 buildings · 55+ gated community
 *
 * FL Statute 718.111(12)(g) compliant
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

define( 'BTG_VERSION', '1.2.0' );
define( 'BTG_PLUGIN_DIR', plugin_dir_path( __FILE__ ) );
define( 'BTG_PLUGIN_URL', plugin_dir_url( __FILE__ ) );

/**
 * ──────────────────────────────────────────────
 *  ACTIVATION — Create all database tables
 * ──────────────────────────────────────────────
 */
function btg_activate() {
    btg_create_tables();
    btg_seed_buildings();
    btg_register_roles();
    add_option( 'btg_db_version', BTG_VERSION );
}
register_activation_hook( __FILE__, 'btg_activate' );

/**
 * Register custom BTG Board Member role and capabilities.
 * - btg_board_member: Can access BTG Admin dashboard only (no WP core admin)
 * - Adds manage_btg capability to Administrator role so admins keep full access
 */
function btg_register_roles() {
    // Ensure administrator has the custom capability
    $admin_role = get_role( 'administrator' );
    if ( $admin_role ) {
        $admin_role->add_cap( 'manage_btg' );
    }

    // Remove and re-add for clean update
    remove_role( 'btg_board_member' );

    // Register BTG Board Member role
    add_role( 'btg_board_member', 'BTG Board Member', array(
        'read'         => true,
        'manage_btg'   => true,
        'upload_files' => true,
    ) );
}

/**
 * Create all custom tables using dbDelta for safe upgrades.
 */
function btg_create_tables() {
    global $wpdb;
    $charset = $wpdb->get_charset_collate();
    $prefix  = $wpdb->prefix . 'btg_';

    require_once ABSPATH . 'wp-admin/includes/upgrade.php';

    // ─── 1. BUILDINGS ───────────────────────────
    $sql = "CREATE TABLE {$prefix}buildings (
        building_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        building_number VARCHAR(10)     NOT NULL,
        building_name   VARCHAR(100)    DEFAULT '',
        address         VARCHAR(255)    NOT NULL DEFAULT '',
        total_units     INT UNSIGNED    NOT NULL DEFAULT 0,
        floors          INT UNSIGNED    NOT NULL DEFAULT 0,
        notes           TEXT            DEFAULT NULL,
        created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (building_id),
        UNIQUE KEY idx_building_number (building_number)
    ) $charset;";
    dbDelta( $sql );

    // ─── 2. UNITS ───────────────────────────────
    $sql = "CREATE TABLE {$prefix}units (
        unit_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        building_id     BIGINT UNSIGNED NOT NULL,
        unit_number     VARCHAR(10)     NOT NULL,
        floor           INT UNSIGNED    DEFAULT NULL,
        bedrooms        TINYINT UNSIGNED DEFAULT NULL,
        bathrooms       DECIMAL(2,1)    DEFAULT NULL,
        sq_ft           INT UNSIGNED    DEFAULT NULL,
        status          ENUM('occupied','vacant','owner-occupied','rented','seasonal') NOT NULL DEFAULT 'occupied',
        notes           TEXT            DEFAULT NULL,
        created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (unit_id),
        UNIQUE KEY idx_building_unit (building_id, unit_number),
        KEY idx_status (status)
    ) $charset;";
    dbDelta( $sql );

    // ─── 3. OWNERS ──────────────────────────────
    $sql = "CREATE TABLE {$prefix}owners (
        owner_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        unit_id             BIGINT UNSIGNED NOT NULL,
        first_name          VARCHAR(100)    NOT NULL,
        last_name           VARCHAR(100)    NOT NULL,
        email               VARCHAR(255)    DEFAULT NULL,
        phone               VARCHAR(20)     DEFAULT NULL,
        phone_secondary     VARCHAR(20)     DEFAULT NULL,
        mailing_address     TEXT            DEFAULT NULL,
        city                VARCHAR(100)    DEFAULT NULL,
        state               VARCHAR(2)      DEFAULT NULL,
        zip                 VARCHAR(10)     DEFAULT NULL,
        is_primary_resident TINYINT(1)      NOT NULL DEFAULT 1,
        is_seasonal         TINYINT(1)      NOT NULL DEFAULT 0,
        seasonal_address    TEXT            DEFAULT NULL,
        move_in_date        DATE            DEFAULT NULL,
        emergency_contact_name  VARCHAR(200) DEFAULT NULL,
        emergency_contact_phone VARCHAR(20)  DEFAULT NULL,
        notes               TEXT            DEFAULT NULL,
        is_active           TINYINT(1)      NOT NULL DEFAULT 1,
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (owner_id),
        KEY idx_unit_id (unit_id),
        KEY idx_name (last_name, first_name),
        KEY idx_email (email),
        KEY idx_active (is_active)
    ) $charset;";
    dbDelta( $sql );

    // ─── 4. RENTERS ─────────────────────────────
    $sql = "CREATE TABLE {$prefix}renters (
        renter_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        unit_id             BIGINT UNSIGNED NOT NULL,
        owner_id            BIGINT UNSIGNED DEFAULT NULL,
        first_name          VARCHAR(100)    NOT NULL,
        last_name           VARCHAR(100)    NOT NULL,
        email               VARCHAR(255)    DEFAULT NULL,
        phone               VARCHAR(20)     DEFAULT NULL,
        lease_start         DATE            DEFAULT NULL,
        lease_end           DATE            DEFAULT NULL,
        monthly_rent        DECIMAL(10,2)   DEFAULT NULL,
        approval_status     ENUM('pending','approved','denied','expired') NOT NULL DEFAULT 'pending',
        approval_date       DATE            DEFAULT NULL,
        application_number  VARCHAR(50)     DEFAULT NULL,
        emergency_contact_name  VARCHAR(200) DEFAULT NULL,
        emergency_contact_phone VARCHAR(20)  DEFAULT NULL,
        num_occupants       TINYINT UNSIGNED DEFAULT 1,
        notes               TEXT            DEFAULT NULL,
        is_active           TINYINT(1)      NOT NULL DEFAULT 1,
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (renter_id),
        KEY idx_unit_id (unit_id),
        KEY idx_owner_id (owner_id),
        KEY idx_name (last_name, first_name),
        KEY idx_lease_end (lease_end),
        KEY idx_status (approval_status),
        KEY idx_active (is_active)
    ) $charset;";
    dbDelta( $sql );

    // ─── 5. PARKING PERMITS ─────────────────────
    $sql = "CREATE TABLE {$prefix}parking_permits (
        permit_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        unit_id         BIGINT UNSIGNED NOT NULL,
        resident_name   VARCHAR(200)    NOT NULL,
        resident_type   ENUM('owner','renter','guest') NOT NULL DEFAULT 'owner',
        vehicle_year    YEAR            DEFAULT NULL,
        vehicle_make    VARCHAR(50)     DEFAULT NULL,
        vehicle_model   VARCHAR(50)     DEFAULT NULL,
        vehicle_color   VARCHAR(30)     DEFAULT NULL,
        license_plate   VARCHAR(15)     NOT NULL,
        plate_state     VARCHAR(2)      NOT NULL DEFAULT 'FL',
        permit_number   VARCHAR(20)     DEFAULT NULL,
        permit_type     ENUM('resident','guest','handicap','temporary') NOT NULL DEFAULT 'resident',
        issued_date     DATE            NOT NULL,
        expiry_date     DATE            DEFAULT NULL,
        status          ENUM('active','expired','revoked','lost') NOT NULL DEFAULT 'active',
        notes           TEXT            DEFAULT NULL,
        created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (permit_id),
        KEY idx_unit_id (unit_id),
        KEY idx_plate (license_plate),
        KEY idx_permit_number (permit_number),
        KEY idx_status (status),
        KEY idx_expiry (expiry_date)
    ) $charset;";
    dbDelta( $sql );

    // ─── 6. BOARD MEMBERS ───────────────────────
    $sql = "CREATE TABLE {$prefix}board_members (
        member_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        owner_id        BIGINT UNSIGNED DEFAULT NULL,
        full_name       VARCHAR(200)    NOT NULL,
        title           VARCHAR(100)    NOT NULL,
        contact_email   VARCHAR(255)    DEFAULT NULL,
        building_number VARCHAR(10)     DEFAULT NULL,
        term_start      DATE            DEFAULT NULL,
        term_end        DATE            DEFAULT NULL,
        committees      VARCHAR(500)    DEFAULT NULL,
        bio             TEXT            DEFAULT NULL,
        display_order   INT UNSIGNED    NOT NULL DEFAULT 0,
        is_active       TINYINT(1)      NOT NULL DEFAULT 1,
        created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (member_id),
        KEY idx_owner_id (owner_id),
        KEY idx_active_order (is_active, display_order)
    ) $charset;";
    dbDelta( $sql );

    // ─── 7. MEETINGS ────────────────────────────
    $sql = "CREATE TABLE {$prefix}meetings (
        meeting_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        meeting_date    DATETIME        NOT NULL,
        meeting_type    ENUM('board','annual','special','committee','budget') NOT NULL DEFAULT 'board',
        title           VARCHAR(255)    NOT NULL DEFAULT '',
        location        VARCHAR(255)    DEFAULT NULL,
        quorum_required INT UNSIGNED    DEFAULT NULL,
        quorum_met      TINYINT(1)      DEFAULT NULL,
        attendee_count  INT UNSIGNED    DEFAULT 0,
        minutes_url     VARCHAR(500)    DEFAULT NULL,
        agenda_url      VARCHAR(500)    DEFAULT NULL,
        notes           TEXT            DEFAULT NULL,
        created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (meeting_id),
        KEY idx_date (meeting_date),
        KEY idx_type (meeting_type)
    ) $charset;";
    dbDelta( $sql );

    // ─── 8. MEETING ATTENDANCE ──────────────────
    $sql = "CREATE TABLE {$prefix}meeting_attendance (
        attendance_id   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        meeting_id      BIGINT UNSIGNED NOT NULL,
        unit_id         BIGINT UNSIGNED DEFAULT NULL,
        attendee_name   VARCHAR(200)    NOT NULL,
        role            ENUM('owner','renter','board_member','proxy','guest','management') NOT NULL DEFAULT 'owner',
        check_in_time   DATETIME        DEFAULT NULL,
        proxy_for       VARCHAR(200)    DEFAULT NULL,
        notes           TEXT            DEFAULT NULL,
        created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (attendance_id),
        KEY idx_meeting_id (meeting_id),
        KEY idx_unit_id (unit_id),
        UNIQUE KEY idx_meeting_unit (meeting_id, unit_id, attendee_name)
    ) $charset;";
    dbDelta( $sql );

    // ─── 9. DOCUMENTS (FL 718.111 Compliance) ───
    $sql = "CREATE TABLE {$prefix}documents (
        doc_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        title           VARCHAR(255)    NOT NULL,
        category        ENUM(
            'governing_docs',
            'financials',
            'budget',
            'meeting_minutes',
            'insurance',
            'contracts',
            'inspection_reports',
            'director_disclosures',
            'rules',
            'forms',
            'notices',
            'other'
        ) NOT NULL DEFAULT 'other',
        description     TEXT            DEFAULT NULL,
        file_path       VARCHAR(500)    NOT NULL,
        file_size       INT UNSIGNED    DEFAULT NULL,
        mime_type       VARCHAR(100)    DEFAULT NULL,
        uploaded_by     BIGINT UNSIGNED DEFAULT NULL,
        upload_date     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        effective_date  DATE            DEFAULT NULL,
        expiry_date     DATE            DEFAULT NULL,
        requires_auth   TINYINT(1)      NOT NULL DEFAULT 1,
        is_active       TINYINT(1)      NOT NULL DEFAULT 1,
        download_count  INT UNSIGNED    NOT NULL DEFAULT 0,
        created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (doc_id),
        KEY idx_category (category),
        KEY idx_active (is_active),
        KEY idx_upload_date (upload_date)
    ) $charset;";
    dbDelta( $sql );

    // ─── 10. EMAIL GROUPS ───────────────────────
    $sql = "CREATE TABLE {$prefix}email_groups (
        group_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        group_name      VARCHAR(100)    NOT NULL,
        group_type      ENUM('all','building','custom','board') NOT NULL DEFAULT 'custom',
        building_id     BIGINT UNSIGNED DEFAULT NULL,
        description     TEXT            DEFAULT NULL,
        member_count    INT UNSIGNED    NOT NULL DEFAULT 0,
        is_active       TINYINT(1)      NOT NULL DEFAULT 1,
        created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (group_id),
        KEY idx_type (group_type),
        KEY idx_building (building_id)
    ) $charset;";
    dbDelta( $sql );

    // ─── 11. EMAIL GROUP MEMBERS (junction) ─────
    $sql = "CREATE TABLE {$prefix}email_group_members (
        id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        group_id        BIGINT UNSIGNED NOT NULL,
        unit_id         BIGINT UNSIGNED DEFAULT NULL,
        email           VARCHAR(255)    NOT NULL,
        first_name      VARCHAR(100)    DEFAULT NULL,
        last_name       VARCHAR(100)    DEFAULT NULL,
        subscribed      TINYINT(1)      NOT NULL DEFAULT 1,
        created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY idx_group_email (group_id, email),
        KEY idx_unit_id (unit_id),
        KEY idx_subscribed (subscribed)
    ) $charset;";
    dbDelta( $sql );

    // ─── 12. EMAIL LOG ──────────────────────────
    $sql = "CREATE TABLE {$prefix}email_log (
        log_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        group_id        BIGINT UNSIGNED DEFAULT NULL,
        subject         VARCHAR(255)    NOT NULL,
        body            LONGTEXT        NOT NULL,
        sent_by         BIGINT UNSIGNED DEFAULT NULL,
        recipient_count INT UNSIGNED    NOT NULL DEFAULT 0,
        sent_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        status          ENUM('sent','failed','partial') NOT NULL DEFAULT 'sent',
        error_message   TEXT            DEFAULT NULL,
        PRIMARY KEY (log_id),
        KEY idx_sent_at (sent_at),
        KEY idx_group_id (group_id)
    ) $charset;";
    dbDelta( $sql );

    // ─── 13. ACTIVITY LOG (audit trail) ─────────
    $sql = "CREATE TABLE {$prefix}activity_log (
        log_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        user_id         BIGINT UNSIGNED DEFAULT NULL,
        action          VARCHAR(50)     NOT NULL,
        entity_type     VARCHAR(50)     NOT NULL,
        entity_id       BIGINT UNSIGNED DEFAULT NULL,
        description     TEXT            DEFAULT NULL,
        ip_address      VARCHAR(45)     DEFAULT NULL,
        created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (log_id),
        KEY idx_user_id (user_id),
        KEY idx_entity (entity_type, entity_id),
        KEY idx_created (created_at)
    ) $charset;";
    dbDelta( $sql );


    // ─── 14. RENTAL APPLICATIONS ────────────────
    $sql = "CREATE TABLE {$prefix}rental_applications (
        app_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        applicant_name  VARCHAR(200)    NOT NULL,
        applicant_email VARCHAR(255)    DEFAULT NULL,
        applicant_phone VARCHAR(20)     DEFAULT NULL,
        building_number VARCHAR(10)     NOT NULL,
        unit_requested  VARCHAR(20)     NOT NULL,
        owner_name      VARCHAR(200)    DEFAULT NULL,
        move_in_date    DATE            DEFAULT NULL,
        lease_term      VARCHAR(50)     DEFAULT NULL,
        num_occupants   TINYINT UNSIGNED DEFAULT 1,
        has_pets        TINYINT(1)      DEFAULT 0,
        pet_details     TEXT            DEFAULT NULL,
        vehicles        TEXT            DEFAULT NULL,
        additional_notes TEXT           DEFAULT NULL,
        status          ENUM('pending','approved','denied') NOT NULL DEFAULT 'pending',
        reviewed_by     BIGINT UNSIGNED DEFAULT NULL,
        reviewed_at     DATETIME        DEFAULT NULL,
        admin_notes     TEXT            DEFAULT NULL,
        submitted_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (app_id),
        KEY idx_status    (status),
        KEY idx_building  (building_number),
        KEY idx_submitted (submitted_at)
    ) $charset;";
    dbDelta( $sql );

    // ─── 15. TRANSFER APPLICATIONS ──────────────
    $sql = "CREATE TABLE {$prefix}transfer_applications (
        app_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        current_owner   VARCHAR(200)    NOT NULL,
        building_number VARCHAR(10)     NOT NULL,
        unit_number     VARCHAR(20)     NOT NULL,
        buyer_name      VARCHAR(200)    NOT NULL,
        buyer_email     VARCHAR(255)    DEFAULT NULL,
        buyer_phone     VARCHAR(20)     DEFAULT NULL,
        closing_date    DATE            DEFAULT NULL,
        title_company   VARCHAR(200)    DEFAULT NULL,
        realtor_name    VARCHAR(200)    DEFAULT NULL,
        realtor_phone   VARCHAR(20)     DEFAULT NULL,
        additional_notes TEXT           DEFAULT NULL,
        status          ENUM('pending','approved','denied') NOT NULL DEFAULT 'pending',
        reviewed_by     BIGINT UNSIGNED DEFAULT NULL,
        reviewed_at     DATETIME        DEFAULT NULL,
        admin_notes     TEXT            DEFAULT NULL,
        submitted_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (app_id),
        KEY idx_status    (status),
        KEY idx_building  (building_number),
        KEY idx_submitted (submitted_at)
    ) $charset;";
    dbDelta( $sql );
}

/**
 * Seed the 13 buildings on activation.
 */
function btg_seed_buildings() {
    global $wpdb;
    $table = $wpdb->prefix . 'btg_buildings';

    // Only seed if empty
    $count = $wpdb->get_var( "SELECT COUNT(*) FROM $table" );
    if ( $count > 0 ) {
        return;
    }

    $buildings = array(
        array( '1',  '9990 Pineapple Tree Dr, Bldg 1,  Boynton Beach, FL 33436' ),
        array( '2',  '9990 Pineapple Tree Dr, Bldg 2,  Boynton Beach, FL 33436' ),
        array( '3',  '9990 Pineapple Tree Dr, Bldg 3,  Boynton Beach, FL 33436' ),
        array( '4',  '9990 Pineapple Tree Dr, Bldg 4,  Boynton Beach, FL 33436' ),
        array( '5',  '9990 Pineapple Tree Dr, Bldg 5,  Boynton Beach, FL 33436' ),
        array( '6',  '9990 Pineapple Tree Dr, Bldg 6,  Boynton Beach, FL 33436' ),
        array( '7',  '9990 Pineapple Tree Dr, Bldg 7,  Boynton Beach, FL 33436' ),
        array( '8',  '9990 Pineapple Tree Dr, Bldg 8,  Boynton Beach, FL 33436' ),
        array( '9',  '9990 Pineapple Tree Dr, Bldg 9,  Boynton Beach, FL 33436' ),
        array( '10', '9990 Pineapple Tree Dr, Bldg 10, Boynton Beach, FL 33436' ),
        array( '11', '9990 Pineapple Tree Dr, Bldg 11, Boynton Beach, FL 33436' ),
        array( '12', '9990 Pineapple Tree Dr, Bldg 12, Boynton Beach, FL 33436' ),
        array( '13', '9990 Pineapple Tree Dr, Bldg 13, Boynton Beach, FL 33436' ),
    );

    foreach ( $buildings as $b ) {
        $wpdb->insert( $table, array(
            'building_number' => $b[0],
            'address'         => $b[1],
        ), array( '%s', '%s' ) );
    }

    // Create default email groups — "All Residents" + one per building
    $groups_table = $wpdb->prefix . 'btg_email_groups';

    $wpdb->insert( $groups_table, array(
        'group_name'  => 'All Residents',
        'group_type'  => 'all',
        'description' => 'All owners and renters across all 13 buildings',
    ) );

    for ( $i = 1; $i <= 13; $i++ ) {
        $wpdb->insert( $groups_table, array(
            'group_name'  => "Building $i",
            'group_type'  => 'building',
            'building_id' => $i,
            'description' => "All residents in Building $i",
        ) );
    }

    // Board Members group
    $wpdb->insert( $groups_table, array(
        'group_name'  => 'Board Members',
        'group_type'  => 'board',
        'description' => 'Current active board members',
    ) );
}

/**
 * ──────────────────────────────────────────────
 *  DEACTIVATION — Clean up (optional)
 * ──────────────────────────────────────────────
 */
function btg_deactivate() {
    // Remove custom capability from administrator
    $admin_role = get_role( 'administrator' );
    if ( $admin_role ) {
        $admin_role->remove_cap( 'manage_btg' );
    }
    // Remove custom role
    remove_role( 'btg_board_member' );
    // Tables persist for safety — drop only via uninstall.php
}
register_deactivation_hook( __FILE__, 'btg_deactivate' );

/**
 * ──────────────────────────────────────────────
 *  VERSION CHECK — Run migrations on update
 * ──────────────────────────────────────────────
 */
function btg_check_version() {
    if ( get_option( 'btg_db_version' ) !== BTG_VERSION ) {
        btg_create_tables();
        btg_register_roles();
        update_option( 'btg_db_version', BTG_VERSION );
    }
}
add_action( 'plugins_loaded', 'btg_check_version' );

/**
 * ──────────────────────────────────────────────
 *  ADMIN MENU
 * ──────────────────────────────────────────────
 */
function btg_admin_menu() {
    // Top-level menu
    add_menu_page(
        'BTG Dashboard',
        'BTG Admin',
        'manage_btg',
        'btg-dashboard',
        'btg_render_dashboard',
        'dashicons-building',
        30
    );

    // Submenu pages
    $subpages = array(
        array( 'btg-owners',          'Owners',          'btg_render_owners' ),
        array( 'btg-renters',         'Renters',         'btg_render_renters' ),
        array( 'btg-parking',         'Parking Permits', 'btg_render_parking' ),
        array( 'btg-board',           'Board Members',   'btg_render_board' ),
        array( 'btg-meetings',        'Meetings',        'btg_render_meetings' ),
        array( 'btg-documents',       'Documents',       'btg_render_documents' ),
        array( 'btg-email-blast',     'Email Blast',     'btg_render_email_blast' ),
        array( 'btg-activity-log',    'Activity Log',    'btg_render_activity_log' ),
        array( 'btg-applications',    'Applications',    'btg_render_applications' ),
    );

    foreach ( $subpages as $sp ) {
        add_submenu_page(
            'btg-dashboard',
            $sp[1],
            $sp[1],
            'manage_btg',
            $sp[0],
            $sp[2]
        );
    }
}
add_action( 'admin_menu', 'btg_admin_menu' );

/**
 * ──────────────────────────────────────────────
 *  BOARD MEMBER RESTRICTIONS
 *  Hide all WordPress core admin menus for users
 *  with manage_btg but NOT manage_options (admins).
 *  Board members see ONLY the BTG Admin menu.
 * ──────────────────────────────────────────────
 */
function btg_restrict_board_menus() {
    // Only restrict users who have manage_btg but NOT full admin
    if ( current_user_can( 'manage_btg' ) && ! current_user_can( 'manage_options' ) ) {
        remove_menu_page( 'index.php' );                // WP Dashboard
        remove_menu_page( 'edit.php' );                 // Posts
        remove_menu_page( 'upload.php' );               // Media
        remove_menu_page( 'edit.php?post_type=page' );  // Pages
        remove_menu_page( 'edit-comments.php' );        // Comments
        remove_menu_page( 'themes.php' );               // Appearance
        remove_menu_page( 'plugins.php' );              // Plugins
        remove_menu_page( 'users.php' );                // Users
        remove_menu_page( 'tools.php' );                // Tools
        remove_menu_page( 'options-general.php' );      // Settings
    }
}
add_action( 'admin_menu', 'btg_restrict_board_menus', 999 );

/**
 * Redirect board members to BTG Dashboard after login
 * (instead of the default WP Dashboard which is hidden for them).
 */
function btg_login_redirect( $redirect_to, $request, $user ) {
    if ( isset( $user->roles ) && is_array( $user->roles ) ) {
        if ( in_array( 'btg_board_member', $user->roles, true ) ) {
            return admin_url( 'admin.php?page=btg-dashboard' );
        }
    }
    return $redirect_to;
}
add_filter( 'login_redirect', 'btg_login_redirect', 10, 3 );

/**
 * Clean up the admin bar for board members.
 * Remove WP logo, + New content, Comments, Updates links.
 */
function btg_admin_bar_cleanup( $wp_admin_bar ) {
    if ( current_user_can( 'manage_btg' ) && ! current_user_can( 'manage_options' ) ) {
        $wp_admin_bar->remove_node( 'new-content' );
        $wp_admin_bar->remove_node( 'comments' );
        $wp_admin_bar->remove_node( 'wp-logo' );
        $wp_admin_bar->remove_node( 'updates' );
    }
}
add_action( 'admin_bar_menu', 'btg_admin_bar_cleanup', 999 );

/**
 * If a board member somehow lands on index.php (WP Dashboard),
 * redirect them to the BTG Dashboard instead.
 */
function btg_redirect_dashboard() {
    global $pagenow;
    if ( $pagenow === 'index.php' && current_user_can( 'manage_btg' ) && ! current_user_can( 'manage_options' ) ) {
        wp_redirect( admin_url( 'admin.php?page=btg-dashboard' ) );
        exit;
    }
}
add_action( 'admin_init', 'btg_redirect_dashboard' );

/**
 * ──────────────────────────────────────────────
 *  DASHBOARD — Main overview page
 * ──────────────────────────────────────────────
 */
function btg_render_dashboard() {
    global $wpdb;
    $p = $wpdb->prefix . 'btg_';

    $total_units    = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$p}units" );
    $total_owners   = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$p}owners WHERE is_active = 1" );
    $total_renters  = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$p}renters WHERE is_active = 1" );
    $total_permits  = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$p}parking_permits WHERE status = 'active'" );
    $total_docs     = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$p}documents WHERE is_active = 1" );
    $total_meetings = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$p}meetings" );

    // Expiring leases in next 30 days
    $expiring_leases = (int) $wpdb->get_var( $wpdb->prepare(
        "SELECT COUNT(*) FROM {$p}renters WHERE is_active = 1 AND lease_end BETWEEN %s AND %s",
        current_time( 'Y-m-d' ),
        date( 'Y-m-d', strtotime( '+30 days' ) )
    ) );

    // Expiring permits in next 30 days
    $expiring_permits = (int) $wpdb->get_var( $wpdb->prepare(
        "SELECT COUNT(*) FROM {$p}parking_permits WHERE status = 'active' AND expiry_date BETWEEN %s AND %s",
        current_time( 'Y-m-d' ),
        date( 'Y-m-d', strtotime( '+30 days' ) )
    ) );

    // Pending applications
    $pending_rental   = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$p}rental_applications WHERE status = 'pending'" );
    $pending_transfer = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$p}transfer_applications WHERE status = 'pending'" );
    $pending_apps     = $pending_rental + $pending_transfer;

    ?>
    <div class="wrap">
        <h1 style="display:flex;align-items:center;gap:10px;">
            <span class="dashicons dashicons-building" style="font-size:28px;width:28px;height:28px;color:#2E7D32;"></span>
            Bent Tree Gardens — Admin Dashboard
        </h1>
        <p style="color:#666;">265 Units · 13 Buildings · Boynton Beach, FL</p>

        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin:24px 0;">
            <?php
            $cards = array(
                array( 'Units',           $total_units,    '#2E7D32', 'dashicons-admin-multisite' ),
                array( 'Active Owners',   $total_owners,   '#1565C0', 'dashicons-groups' ),
                array( 'Active Renters',  $total_renters,  '#6A1B9A', 'dashicons-id' ),
                array( 'Parking Permits', $total_permits,  '#E65100', 'dashicons-car' ),
                array( 'Documents',       $total_docs,     '#C8A951', 'dashicons-media-document' ),
                array( 'Meetings',        $total_meetings, '#00695C', 'dashicons-calendar-alt' ),
                array( 'Pending Apps',   $pending_apps,   '#E65100', 'dashicons-clipboard' ),
            );
            foreach ( $cards as $c ) :
            ?>
            <div style="background:#fff;border-radius:8px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);border-left:4px solid <?php echo $c[2]; ?>;">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                    <span class="dashicons <?php echo $c[3]; ?>" style="color:<?php echo $c[2]; ?>;"></span>
                    <span style="color:#666;font-size:13px;"><?php echo $c[0]; ?></span>
                </div>
                <div style="font-size:28px;font-weight:700;color:<?php echo $c[2]; ?>;"><?php echo $c[1]; ?></div>
            </div>
            <?php endforeach; ?>
        </div>

        <?php if ( $expiring_leases > 0 || $expiring_permits > 0 ) : ?>
        <div style="background:#FFF3E0;border-left:4px solid #E65100;border-radius:8px;padding:16px;margin-bottom:20px;">
            <strong style="color:#E65100;">Upcoming Expirations (Next 30 Days)</strong>
            <ul style="margin:8px 0 0 20px;">
                <?php if ( $expiring_leases > 0 ) : ?>
                    <li><?php echo $expiring_leases; ?> lease(s) expiring</li>
                <?php endif; ?>
                <?php if ( $expiring_permits > 0 ) : ?>
                    <li><?php echo $expiring_permits; ?> parking permit(s) expiring</li>
                <?php endif; ?>
            </ul>
        </div>
        <?php endif; ?>

        <!-- Building Breakdown -->
        <div style="background:#fff;border-radius:8px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:20px;">
            <h2 style="font-size:16px;color:#1B5E20;margin:0 0 16px;">Residents by Building</h2>
            <table class="widefat striped">
                <thead>
                    <tr>
                        <th>Building</th>
                        <th>Units</th>
                        <th>Owners</th>
                        <th>Renters</th>
                        <th>Permits</th>
                    </tr>
                </thead>
                <tbody>
                    <?php
                    $buildings = $wpdb->get_results( "SELECT * FROM {$p}buildings ORDER BY CAST(building_number AS UNSIGNED)" );
                    foreach ( $buildings as $bldg ) :
                        $b_units   = (int) $wpdb->get_var( $wpdb->prepare( "SELECT COUNT(*) FROM {$p}units WHERE building_id = %d", $bldg->building_id ) );
                        $b_owners  = (int) $wpdb->get_var( $wpdb->prepare(
                            "SELECT COUNT(*) FROM {$p}owners o JOIN {$p}units u ON o.unit_id = u.unit_id WHERE u.building_id = %d AND o.is_active = 1",
                            $bldg->building_id
                        ) );
                        $b_renters = (int) $wpdb->get_var( $wpdb->prepare(
                            "SELECT COUNT(*) FROM {$p}renters r JOIN {$p}units u ON r.unit_id = u.unit_id WHERE u.building_id = %d AND r.is_active = 1",
                            $bldg->building_id
                        ) );
                        $b_permits = (int) $wpdb->get_var( $wpdb->prepare(
                            "SELECT COUNT(*) FROM {$p}parking_permits p JOIN {$p}units u ON p.unit_id = u.unit_id WHERE u.building_id = %d AND p.status = 'active'",
                            $bldg->building_id
                        ) );
                    ?>
                    <tr>
                        <td><strong>Building <?php echo esc_html( $bldg->building_number ); ?></strong></td>
                        <td><?php echo $b_units; ?></td>
                        <td><?php echo $b_owners; ?></td>
                        <td><?php echo $b_renters; ?></td>
                        <td><?php echo $b_permits; ?></td>
                    </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        </div>
    </div>
    <?php
}

/**
 * ──────────────────────────────────────────────
 *  PLACEHOLDER RENDER FUNCTIONS
 *  Each will be expanded into full CRUD pages
 * ──────────────────────────────────────────────
 */
function btg_render_owners() {
    global $wpdb;
    $p = $wpdb->prefix . "btg_";
    $buildings = $wpdb->get_results("SELECT building_id, building_number, building_name FROM {$p}buildings ORDER BY building_number+0", ARRAY_A);
    ?>
    <div class="wrap">
    <h1>Owners <a href="#" class="page-title-action" id="btg-add-owner">Add New</a></h1>
    <p>Manage all unit owners — add, edit, search, filter by building.</p>
    <div style="margin:15px 0;display:flex;gap:10px;align-items:center">
        <select id="btg-bldg-filter"><option value="">All Buildings</option>
        <?php foreach($buildings as $b) echo '<option value="'.$b['building_number'].'">Building '.$b['building_number'].'</option>'; ?>
        </select>
        <input type="text" id="btg-search" placeholder="Search name, email, phone..." style="width:300px" class="regular-text">
        <span id="btg-count" style="color:#666"></span>
    </div>
    <table class="wp-list-table widefat fixed striped" id="btg-owners-table">
    <thead><tr><th style="width:90px">Unit</th><th>Name</th><th>Email</th><th>Phone</th><th style="width:70px">Primary</th><th style="width:120px">Actions</th></tr></thead>
    <tbody id="btg-owners-body"><tr><td colspan="6">Loading...</td></tr></tbody>
    </table>
    </div>
    <div id="btg-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);z-index:100000">
    <div style="background:#fff;width:500px;margin:80px auto;border-radius:8px;padding:0">
        <div style="padding:15px 20px;border-bottom:1px solid #ddd;display:flex;justify-content:space-between;align-items:center">
            <h2 id="btg-modal-title" style="margin:0">Add Owner</h2>
            <button type="button" class="btg-close" style="background:none;border:none;font-size:20px;cursor:pointer">&times;</button>
        </div>
        <form id="btg-owner-form" style="padding:20px">
            <input type="hidden" name="owner_id" id="f-owner-id">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Building*</label>
                <select name="building_number" id="f-building" required style="width:100%">
                    <option value="">Select...</option>
                    <?php foreach($buildings as $b) echo '<option value="'.$b['building_number'].'">Building '.$b['building_number'].'</option>'; ?>
                </select></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Unit #*</label>
                <input type="text" name="unit_number" id="f-unit" required class="regular-text" style="width:100%" placeholder="e.g. 101"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">First Name*</label>
                <input type="text" name="first_name" id="f-fname" required class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Last Name*</label>
                <input type="text" name="last_name" id="f-lname" required class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Email</label>
                <input type="email" name="email" id="f-email" class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Phone</label>
                <input type="text" name="phone" id="f-phone" class="regular-text" style="width:100%"></div>
                <div style="grid-column:span 2"><label><input type="checkbox" name="is_primary" id="f-primary" value="1" checked> Primary Resident</label></div>
            </div>
            <div style="margin-top:20px;text-align:right">
                <button type="button" class="button btg-close">Cancel</button>
                <button type="submit" class="button button-primary" style="margin-left:8px">Save Owner</button>
            </div>
        </form>
    </div></div>
    <script>
    jQuery(function($){
        var owners=[];
        function load(){
            $.post(ajaxurl,{action:'btg_crud_owners',sub:'list'},function(r){
                if(r.success){owners=r.data;render();}
            });
        }
        function render(){
            var b=$('#btg-bldg-filter').val(), s=$('#btg-search').val().toLowerCase(), rows=owners;
            if(b) rows=rows.filter(function(o){return o.building_number==b;});
            if(s) rows=rows.filter(function(o){return (o.first_name+' '+o.last_name+' '+o.email+' '+o.phone).toLowerCase().indexOf(s)>=0;});
            $('#btg-count').text(rows.length+' of '+owners.length+' owners');
            if(!rows.length){$('#btg-owners-body').html('<tr><td colspan="6">No owners found.</td></tr>');return;}
            var h='';
            rows.forEach(function(o){
                h+='<tr><td><strong>'+o.building_number+'-'+o.unit_number+'</strong></td>';
                h+='<td>'+o.first_name+' '+o.last_name+'</td>';
                h+='<td>'+(o.email||'—')+'</td>';
                h+='<td>'+(o.phone||'—')+'</td>';
                h+='<td>'+(o.is_primary_resident=='1'?'Yes':'No')+'</td>';
                h+='<td><a href="#" class="btg-edit" data-id="'+o.owner_id+'">Edit</a> | <a href="#" class="btg-del" data-id="'+o.owner_id+'" style="color:#a00">Delete</a></td></tr>';
            });
            $('#btg-owners-body').html(h);
        }
        $('#btg-bldg-filter,#btg-search').on('change keyup',render);
        $('#btg-add-owner').on('click',function(e){
            e.preventDefault();$('#btg-modal-title').text('Add Owner');
            $('#btg-owner-form')[0].reset();$('#f-owner-id').val('');$('#f-primary').prop('checked',true);
            $('#btg-modal').fadeIn(150);
        });
        $(document).on('click','.btg-close',function(){$('#btg-modal').fadeOut(150);});
        $(document).on('click','.btg-edit',function(e){
            e.preventDefault();var id=$(this).data('id');
            var o=owners.find(function(x){return x.owner_id==id;});
            if(!o)return;
            $('#btg-modal-title').text('Edit Owner');
            $('#f-owner-id').val(o.owner_id);$('#f-building').val(o.building_number);
            $('#f-unit').val(o.unit_number);$('#f-fname').val(o.first_name);$('#f-lname').val(o.last_name);
            $('#f-email').val(o.email);$('#f-phone').val(o.phone);
            $('#f-primary').prop('checked',o.is_primary_resident=='1');
            $('#btg-modal').fadeIn(150);
        });
        $(document).on('click','.btg-del',function(e){
            e.preventDefault();if(!confirm('Delete this owner?'))return;
            $.post(ajaxurl,{action:'btg_crud_owners',sub:'delete',owner_id:$(this).data('id')},function(r){
                if(r.success)load();else alert(r.data||'Error');
            });
        });
        $('#btg-owner-form').on('submit',function(e){
            e.preventDefault();var d=$(this).serializeArray();
            d.push({name:'action',value:'btg_crud_owners'},{name:'sub',value:'save'});
            if(!$('#f-primary').is(':checked')) d.push({name:'is_primary',value:'0'});
            $.post(ajaxurl,$.param(d),function(r){
                if(r.success){$('#btg-modal').fadeOut(150);load();}else alert(r.data||'Error');
            });
        });
        load();
    });
    </script>
    <?php
}

function btg_render_renters() {
    global $wpdb;
    $p = $wpdb->prefix . "btg_";
    $buildings = $wpdb->get_results("SELECT building_id, building_number FROM {$p}buildings ORDER BY building_number+0", ARRAY_A);
    ?>
    <div class="wrap">
    <h1>Renters <a href="#" class="page-title-action" id="btg-add-renter">Add New</a></h1>
    <p>Manage all renters — add, edit, search, filter by building.</p>
    <div style="margin:15px 0;display:flex;gap:10px;align-items:center">
        <select id="btg-bldg-filter"><option value="">All Buildings</option>
        <?php foreach($buildings as $b) echo '<option value="'.$b['building_number'].'">Building '.$b['building_number'].'</option>'; ?>
        </select>
        <input type="text" id="btg-search" placeholder="Search name, email, phone..." style="width:300px" class="regular-text">
        <span id="btg-count" style="color:#666"></span>
    </div>
    <table class="wp-list-table widefat fixed striped" id="btg-renters-table">
    <thead><tr><th style="width:90px">Unit</th><th>Name</th><th>Email</th><th>Phone</th><th style="width:120px">Actions</th></tr></thead>
    <tbody id="btg-renters-body"><tr><td colspan="5">Loading...</td></tr></tbody>
    </table>
    </div>
    <div id="btg-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);z-index:100000">
    <div style="background:#fff;width:500px;margin:80px auto;border-radius:8px;padding:0">
        <div style="padding:15px 20px;border-bottom:1px solid #ddd;display:flex;justify-content:space-between;align-items:center">
            <h2 id="btg-modal-title" style="margin:0">Add Renter</h2>
            <button type="button" class="btg-close" style="background:none;border:none;font-size:20px;cursor:pointer">&times;</button>
        </div>
        <form id="btg-renter-form" style="padding:20px">
            <input type="hidden" name="renter_id" id="f-renter-id">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Building*</label>
                <select name="building_number" id="f-building" required style="width:100%">
                    <option value="">Select...</option>
                    <?php foreach($buildings as $b) echo '<option value="'.$b['building_number'].'">Building '.$b['building_number'].'</option>'; ?>
                </select></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Unit #*</label>
                <input type="text" name="unit_number" id="f-unit" required class="regular-text" style="width:100%" placeholder="e.g. 101"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">First Name*</label>
                <input type="text" name="first_name" id="f-fname" required class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Last Name*</label>
                <input type="text" name="last_name" id="f-lname" required class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Email</label>
                <input type="email" name="email" id="f-email" class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Phone</label>
                <input type="text" name="phone" id="f-phone" class="regular-text" style="width:100%"></div>
            </div>
            <div style="margin-top:20px;text-align:right">
                <button type="button" class="button btg-close">Cancel</button>
                <button type="submit" class="button button-primary" style="margin-left:8px">Save Renter</button>
            </div>
        </form>
    </div></div>
    <script>
    jQuery(function($){
        var renters=[];
        function load(){
            $.post(ajaxurl,{action:'btg_crud_renters',sub:'list'},function(r){
                if(r.success){renters=r.data;render();}
            });
        }
        function render(){
            var b=$('#btg-bldg-filter').val(), s=$('#btg-search').val().toLowerCase(), rows=renters;
            if(b) rows=rows.filter(function(o){return o.building_number==b;});
            if(s) rows=rows.filter(function(o){return (o.first_name+' '+o.last_name+' '+o.email+' '+o.phone).toLowerCase().indexOf(s)>=0;});
            $('#btg-count').text(rows.length+' of '+renters.length+' renters');
            if(!rows.length){$('#btg-renters-body').html('<tr><td colspan="5">No renters found.</td></tr>');return;}
            var h='';
            rows.forEach(function(o){
                h+='<tr><td><strong>'+o.building_number+'-'+o.unit_number+'</strong></td>';
                h+='<td>'+o.first_name+' '+o.last_name+'</td>';
                h+='<td>'+(o.email||'—')+'</td>';
                h+='<td>'+(o.phone||'—')+'</td>';
                h+='<td><a href="#" class="btg-edit" data-id="'+o.renter_id+'">Edit</a> | <a href="#" class="btg-del" data-id="'+o.renter_id+'" style="color:#a00">Delete</a></td></tr>';
            });
            $('#btg-renters-body').html(h);
        }
        $('#btg-bldg-filter,#btg-search').on('change keyup',render);
        $('#btg-add-renter').on('click',function(e){
            e.preventDefault();$('#btg-modal-title').text('Add Renter');
            $('#btg-renter-form')[0].reset();$('#f-renter-id').val('');
            $('#btg-modal').fadeIn(150);
        });
        $(document).on('click','.btg-close',function(){$('#btg-modal').fadeOut(150);});
        $(document).on('click','.btg-edit',function(e){
            e.preventDefault();var id=$(this).data('id');
            var o=renters.find(function(x){return x.renter_id==id;});
            if(!o)return;
            $('#btg-modal-title').text('Edit Renter');
            $('#f-renter-id').val(o.renter_id);$('#f-building').val(o.building_number);
            $('#f-unit').val(o.unit_number);$('#f-fname').val(o.first_name);$('#f-lname').val(o.last_name);
            $('#f-email').val(o.email);$('#f-phone').val(o.phone);
            $('#btg-modal').fadeIn(150);
        });
        $(document).on('click','.btg-del',function(e){
            e.preventDefault();if(!confirm('Delete this renter?'))return;
            $.post(ajaxurl,{action:'btg_crud_renters',sub:'delete',renter_id:$(this).data('id')},function(r){
                if(r.success)load();else alert(r.data||'Error');
            });
        });
        $('#btg-renter-form').on('submit',function(e){
            e.preventDefault();var d=$(this).serializeArray();
            d.push({name:'action',value:'btg_crud_renters'},{name:'sub',value:'save'});
            $.post(ajaxurl,$.param(d),function(r){
                if(r.success){$('#btg-modal').fadeOut(150);load();}else alert(r.data||'Error');
            });
        });
        load();
    });
    </script>
    <?php
}

function btg_render_parking() {
    global $wpdb;
    $p = $wpdb->prefix . "btg_";
    $buildings = $wpdb->get_results("SELECT building_id, building_number FROM {$p}buildings ORDER BY building_number+0", ARRAY_A);
    ?>
    <div class="wrap">
    <h1>Parking Permits <a href="#" class="page-title-action" id="btg-add-permit">Add New</a></h1>
    <p>Manage all parking permits — add, edit, search, filter by building.</p>
    <div style="margin:15px 0;display:flex;gap:10px;align-items:center">
        <select id="btg-bldg-filter"><option value="">All Buildings</option>
        <?php foreach($buildings as $b) echo '<option value="'.$b['building_number'].'">Building '.$b['building_number'].'</option>'; ?>
        </select>
        <input type="text" id="btg-search" placeholder="Search name, plate, vehicle..." style="width:300px" class="regular-text">
        <span id="btg-count" style="color:#666"></span>
    </div>
    <table class="wp-list-table widefat fixed striped" id="btg-permits-table">
    <thead><tr><th style="width:70px">Unit</th><th>Resident</th><th>Vehicle</th><th style="width:90px">Color</th><th style="width:100px">Plate</th><th style="width:80px">Permit #</th><th style="width:70px">Status</th><th style="width:110px">Actions</th></tr></thead>
    <tbody id="btg-permits-body"><tr><td colspan="8">Loading...</td></tr></tbody>
    </table>
    </div>
    <div id="btg-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);z-index:100000">
    <div style="background:#fff;width:560px;margin:60px auto;border-radius:8px;padding:0">
        <div style="padding:15px 20px;border-bottom:1px solid #ddd;display:flex;justify-content:space-between;align-items:center">
            <h2 id="btg-modal-title" style="margin:0">Add Permit</h2>
            <button type="button" class="btg-close" style="background:none;border:none;font-size:20px;cursor:pointer">&times;</button>
        </div>
        <form id="btg-permit-form" style="padding:20px">
            <input type="hidden" name="permit_id" id="f-permit-id">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Building*</label>
                <select name="building_number" id="f-building" required style="width:100%">
                    <option value="">Select...</option>
                    <?php foreach($buildings as $b) echo '<option value="'.$b['building_number'].'">Building '.$b['building_number'].'</option>'; ?>
                </select></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Unit #*</label>
                <input type="text" name="unit_number" id="f-unit" required class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Resident Name*</label>
                <input type="text" name="resident_name" id="f-name" required class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Type</label>
                <select name="resident_type" id="f-type" style="width:100%">
                    <option value="owner">Owner</option><option value="renter">Renter</option>
                </select></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Vehicle Make</label>
                <input type="text" name="vehicle_make" id="f-make" class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Vehicle Model</label>
                <input type="text" name="vehicle_model" id="f-model" class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Vehicle Color</label>
                <input type="text" name="vehicle_color" id="f-color" class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">License Plate</label>
                <input type="text" name="license_plate" id="f-plate" class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Permit Number</label>
                <input type="text" name="permit_number" id="f-permit" class="regular-text" style="width:100%"></div>
            </div>
            <div style="margin-top:20px;text-align:right">
                <button type="button" class="button btg-close">Cancel</button>
                <button type="submit" class="button button-primary" style="margin-left:8px">Save Permit</button>
            </div>
        </form>
    </div></div>
    <script>
    jQuery(function($){
        var permits=[];
        function load(){
            $.post(ajaxurl,{action:'btg_crud_permits',sub:'list'},function(r){
                if(r.success){permits=r.data;render();}
            });
        }
        function render(){
            var b=$('#btg-bldg-filter').val(), s=$('#btg-search').val().toLowerCase(), rows=permits;
            if(b) rows=rows.filter(function(o){return o.building_number==b;});
            if(s) rows=rows.filter(function(o){return (o.resident_name+' '+o.vehicle_make+' '+o.vehicle_model+' '+o.license_plate+' '+o.vehicle_color).toLowerCase().indexOf(s)>=0;});
            $('#btg-count').text(rows.length+' of '+permits.length+' permits');
            if(!rows.length){$('#btg-permits-body').html('<tr><td colspan="8">No permits found.</td></tr>');return;}
            var h='';
            rows.forEach(function(o){
                h+='<tr><td><strong>'+o.building_number+'-'+o.unit_number+'</strong></td>';
                h+='<td>'+o.resident_name+'</td>';
                h+='<td>'+(o.vehicle_make||'')+' '+(o.vehicle_model||'')+'</td>';
                h+='<td>'+(o.vehicle_color||'—')+'</td>';
                h+='<td>'+(o.license_plate||'—')+'</td>';
                h+='<td>'+(o.permit_number||'—')+'</td>';
                h+='<td>'+(o.status||'active')+'</td>';
                h+='<td><a href="#" class="btg-edit" data-id="'+o.permit_id+'">Edit</a> | <a href="#" class="btg-del" data-id="'+o.permit_id+'" style="color:#a00">Delete</a></td></tr>';
            });
            $('#btg-permits-body').html(h);
        }
        $('#btg-bldg-filter,#btg-search').on('change keyup',render);
        $('#btg-add-permit').on('click',function(e){
            e.preventDefault();$('#btg-modal-title').text('Add Permit');
            $('#btg-permit-form')[0].reset();$('#f-permit-id').val('');
            $('#btg-modal').fadeIn(150);
        });
        $(document).on('click','.btg-close',function(){$('#btg-modal').fadeOut(150);});
        $(document).on('click','.btg-edit',function(e){
            e.preventDefault();var id=$(this).data('id');
            var o=permits.find(function(x){return x.permit_id==id;});
            if(!o)return;
            $('#btg-modal-title').text('Edit Permit');
            $('#f-permit-id').val(o.permit_id);$('#f-building').val(o.building_number);
            $('#f-unit').val(o.unit_number);$('#f-name').val(o.resident_name);$('#f-type').val(o.resident_type);
            $('#f-make').val(o.vehicle_make);$('#f-model').val(o.vehicle_model);$('#f-color').val(o.vehicle_color);
            $('#f-plate').val(o.license_plate);$('#f-permit').val(o.permit_number);
            $('#btg-modal').fadeIn(150);
        });
        $(document).on('click','.btg-del',function(e){
            e.preventDefault();if(!confirm('Delete this permit?'))return;
            $.post(ajaxurl,{action:'btg_crud_permits',sub:'delete',permit_id:$(this).data('id')},function(r){
                if(r.success)load();else alert(r.data||'Error');
            });
        });
        $('#btg-permit-form').on('submit',function(e){
            e.preventDefault();var d=$(this).serializeArray();
            d.push({name:'action',value:'btg_crud_permits'},{name:'sub',value:'save'});
            $.post(ajaxurl,$.param(d),function(r){
                if(r.success){$('#btg-modal').fadeOut(150);load();}else alert(r.data||'Error');
            });
        });
        load();
    });
    </script>
    <?php
}

function btg_render_board() {
    ?>
    <div class="wrap">
    <h1>Board Members <a href="#" class="page-title-action" id="btg-add-board">Add New</a></h1>
    <p>Manage board member profiles displayed on the public website.</p>
    <div style="margin:15px 0;display:flex;gap:10px;align-items:center">
        <select id="btg-status-filter">
            <option value="active">Active Members</option>
            <option value="all">All Members</option>
            <option value="inactive">Inactive Only</option>
        </select>
        <input type="text" id="btg-search" placeholder="Search name, title, email..." style="width:300px" class="regular-text">
        <span id="btg-count" style="color:#666"></span>
    </div>
    <table class="wp-list-table widefat fixed striped" id="btg-board-table">
    <thead><tr>
        <th style="width:40px">Order</th>
        <th>Name</th>
        <th>Title / Role</th>
        <th>Email</th>
        <th style="width:80px">Building</th>
        <th style="width:90px">Term Ends</th>
        <th style="width:60px">Active</th>
        <th style="width:120px">Actions</th>
    </tr></thead>
    <tbody id="btg-board-body"><tr><td colspan="8">Loading...</td></tr></tbody>
    </table>
    </div>

    <!-- Add/Edit Modal -->
    <div id="btg-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);z-index:100000">
    <div style="background:#fff;width:580px;margin:40px auto;border-radius:8px;padding:0;max-height:90vh;overflow-y:auto">
        <div style="padding:15px 20px;border-bottom:1px solid #ddd;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;background:#fff;z-index:1">
            <h2 id="btg-modal-title" style="margin:0">Add Board Member</h2>
            <button type="button" class="btg-close" style="background:none;border:none;font-size:20px;cursor:pointer">&times;</button>
        </div>
        <form id="btg-board-form" style="padding:20px">
            <input type="hidden" name="member_id" id="f-member-id">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                <div style="grid-column:span 2"><label style="font-weight:600;display:block;margin-bottom:4px">Full Name*</label>
                <input type="text" name="full_name" id="f-name" required class="regular-text" style="width:100%" placeholder="e.g. John Smith"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px">Title / Role*</label>
                <select name="title" id="f-title" required style="width:100%">
                    <option value="">Select...</option>
                    <option value="President">President</option>
                    <option value="Vice President">Vice President</option>
                    <option value="Secretary">Secretary</option>
                    <option value="Treasurer">Treasurer</option>
                    <option value="Director">Director</option>
                    <option value="Director at Large">Director at Large</option>
                    <option value="Member">Member</option>
                </select></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px">Contact Email</label>
                <input type="email" name="contact_email" id="f-email" class="regular-text" style="width:100%"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px">Building #</label>
                <input type="text" name="building_number" id="f-building" class="regular-text" style="width:100%" placeholder="e.g. 4"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px">Display Order</label>
                <input type="number" name="display_order" id="f-order" class="regular-text" style="width:100%" value="0" min="0" max="99">
                <small style="color:#666">Lower numbers appear first on the website</small></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px">Term Start</label>
                <input type="date" name="term_start" id="f-term-start" class="regular-text" style="width:100%"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px">Term End</label>
                <input type="date" name="term_end" id="f-term-end" class="regular-text" style="width:100%"></div>

                <div style="grid-column:span 2"><label style="font-weight:600;display:block;margin-bottom:4px">Committees</label>
                <input type="text" name="committees" id="f-committees" class="regular-text" style="width:100%" placeholder="e.g. Landscape, Budget, Rules"></div>

                <div style="grid-column:span 2"><label style="font-weight:600;display:block;margin-bottom:4px">Bio</label>
                <textarea name="bio" id="f-bio" rows="3" class="regular-text" style="width:100%" placeholder="Short biography for the public website..."></textarea></div>

                <div style="grid-column:span 2"><label><input type="checkbox" name="is_active" id="f-active" value="1" checked> Active (shown on public website)</label></div>
            </div>
            <div style="margin-top:20px;text-align:right">
                <button type="button" class="button btg-close">Cancel</button>
                <button type="submit" class="button button-primary" style="margin-left:8px">Save Board Member</button>
            </div>
        </form>
    </div></div>

    <script>
    jQuery(function($){
        var members=[];
        function load(){
            $.post(ajaxurl,{action:'btg_crud_board',sub:'list'},function(r){
                if(r.success){members=r.data;render();}
            });
        }
        function render(){
            var st=$('#btg-status-filter').val(), s=$('#btg-search').val().toLowerCase(), rows=members;
            if(st==='active') rows=rows.filter(function(m){return m.is_active==='1'||m.is_active===1;});
            if(st==='inactive') rows=rows.filter(function(m){return m.is_active==='0'||m.is_active===0;});
            if(s) rows=rows.filter(function(m){return(m.full_name+' '+m.title+' '+(m.contact_email||'')+' '+(m.committees||'')).toLowerCase().indexOf(s)>=0;});
            $('#btg-count').text(rows.length+' member'+(rows.length!==1?'s':''));
            if(!rows.length){$('#btg-board-body').html('<tr><td colspan="8">No board members found.</td></tr>');return;}
            var h='';
            rows.forEach(function(m){
                var active=m.is_active==='1'||m.is_active===1;
                h+='<tr'+(active?'':' style="opacity:.5"')+'>';
                h+='<td>'+m.display_order+'</td>';
                h+='<td><strong>'+m.full_name+'</strong></td>';
                h+='<td>'+m.title+'</td>';
                h+='<td>'+(m.contact_email||'—')+'</td>';
                h+='<td>'+(m.building_number?'Bldg '+m.building_number:'—')+'</td>';
                h+='<td>'+(m.term_end||'—')+'</td>';
                h+='<td>'+(active?'<span style="color:#2E7D32;font-weight:600">Yes</span>':'<span style="color:#999">No</span>')+'</td>';
                h+='<td><a href="#" class="btg-edit" data-id="'+m.member_id+'">Edit</a> | <a href="#" class="btg-del" data-id="'+m.member_id+'" data-name="'+m.full_name+'" style="color:#a00">Delete</a></td>';
                h+='</tr>';
            });
            $('#btg-board-body').html(h);
        }
        $('#btg-status-filter,#btg-search').on('change keyup',render);

        // Add
        $('#btg-add-board').on('click',function(e){
            e.preventDefault();$('#btg-modal-title').text('Add Board Member');
            $('#btg-board-form')[0].reset();$('#f-member-id').val('');
            $('#f-active').prop('checked',true);$('#f-order').val(0);
            $('#btg-modal').fadeIn(150);
        });

        // Close
        $(document).on('click','.btg-close',function(){$('#btg-modal').fadeOut(150);});

        // Edit
        $(document).on('click','.btg-edit',function(e){
            e.preventDefault();var id=$(this).data('id');
            var m=members.find(function(x){return x.member_id==id;});
            if(!m)return;
            $('#btg-modal-title').text('Edit Board Member');
            $('#f-member-id').val(m.member_id);
            $('#f-name').val(m.full_name);
            // Set title — if value not in dropdown, add it
            if($('#f-title option[value="'+m.title+'"]').length){
                $('#f-title').val(m.title);
            } else {
                $('#f-title').append('<option value="'+m.title+'">'+m.title+'</option>').val(m.title);
            }
            $('#f-email').val(m.contact_email||'');
            $('#f-building').val(m.building_number||'');
            $('#f-order').val(m.display_order||0);
            $('#f-term-start').val(m.term_start||'');
            $('#f-term-end').val(m.term_end||'');
            $('#f-committees').val(m.committees||'');
            $('#f-bio').val(m.bio||'');
            $('#f-active').prop('checked',m.is_active==='1'||m.is_active===1);
            $('#btg-modal').fadeIn(150);
        });

        // Delete
        $(document).on('click','.btg-del',function(e){
            e.preventDefault();
            var name=$(this).data('name');
            if(!confirm('Delete board member "'+name+'"? This cannot be undone.'))return;
            $.post(ajaxurl,{action:'btg_crud_board',sub:'delete',member_id:$(this).data('id')},function(r){
                if(r.success)load();else alert(r.data||'Error');
            });
        });

        // Save
        $('#btg-board-form').on('submit',function(e){
            e.preventDefault();var d=$(this).serializeArray();
            d.push({name:'action',value:'btg_crud_board'},{name:'sub',value:'save'});
            if(!$('#f-active').is(':checked')) d.push({name:'is_active',value:'0'});
            $.post(ajaxurl,$.param(d),function(r){
                if(r.success){$('#btg-modal').fadeOut(150);load();}else alert(r.data||'Error');
            });
        });
        load();
    });
    </script>
    <?php
}
// ============================================
// MEETINGS & ATTENDANCE
// ============================================

function btg_ensure_meeting_tables() {
    global $wpdb;
    $charset = $wpdb->get_charset_collate();
    $p = $wpdb->prefix . "btg_";
    require_once ABSPATH . 'wp-admin/includes/upgrade.php';
    
    $sql1 = "CREATE TABLE IF NOT EXISTS {$p}meetings (
        meeting_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        title VARCHAR(255) NOT NULL,
        meeting_date DATE NOT NULL,
        meeting_type VARCHAR(50) DEFAULT 'general',
        location VARCHAR(255) DEFAULT '',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (meeting_id)
    ) $charset;";
    dbDelta($sql1);
    
    $sql2 = "CREATE TABLE IF NOT EXISTS {$p}meeting_attendance (
        attendance_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        meeting_id BIGINT UNSIGNED NOT NULL,
        unit_id BIGINT UNSIGNED DEFAULT NULL,
        attendee_name VARCHAR(255) NOT NULL,
        attendee_name_2 VARCHAR(255) DEFAULT '',
        signed_in TINYINT(1) DEFAULT 1,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (attendance_id),
        KEY meeting_id (meeting_id),
        KEY unit_id (unit_id)
    ) $charset;";
    dbDelta($sql2);
}

function btg_ensure_documents_table() {
    global $wpdb;
    $charset = $wpdb->get_charset_collate();
    $p = $wpdb->prefix . "btg_";
    require_once ABSPATH . 'wp-admin/includes/upgrade.php';
    
    $sql = "CREATE TABLE IF NOT EXISTS {$p}documents (
        document_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        title VARCHAR(255) NOT NULL,
        description TEXT DEFAULT '',
        file_path VARCHAR(500) NOT NULL,
        file_url VARCHAR(500) NOT NULL,
        file_type VARCHAR(50) DEFAULT '',
        file_size BIGINT DEFAULT 0,
        category VARCHAR(100) DEFAULT 'general',
        uploaded_by BIGINT UNSIGNED DEFAULT NULL,
        requires_auth TINYINT(1) DEFAULT 0,
        is_active TINYINT(1) DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (document_id)
    ) $charset;";
    dbDelta($sql);

    // Ensure requires_auth column exists (safe to run multiple times)
    $col_exists = $wpdb->get_results("SHOW COLUMNS FROM {$p}documents LIKE 'requires_auth'");
    if(empty($col_exists)){
        $wpdb->query("ALTER TABLE {$p}documents ADD COLUMN requires_auth TINYINT(1) DEFAULT 0 AFTER file_size");
    }
}

function btg_render_meetings() {
    global $wpdb;
    btg_ensure_meeting_tables();
    $p = $wpdb->prefix . "btg_";
    $meetings = $wpdb->get_results("SELECT * FROM {$p}meetings ORDER BY meeting_date DESC", ARRAY_A);
    ?>
    <div class="wrap">
    <h1>Meetings <a href="#" class="page-title-action" id="btg-add-meeting">Add New</a></h1>
    <p>Track board meetings, general assemblies, and attendance records.</p>
    <table class="wp-list-table widefat fixed striped" id="btg-meetings-table">
    <thead><tr><th>Date</th><th>Title</th><th>Type</th><th>Attendance</th><th style="width:180px">Actions</th></tr></thead>
    <tbody id="btg-meetings-body"><tr><td colspan="5">Loading...</td></tr></tbody>
    </table>
    </div>
    <div id="btg-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);z-index:100000">
    <div style="background:#fff;width:500px;margin:80px auto;border-radius:8px;padding:0">
        <div style="padding:15px 20px;border-bottom:1px solid #ddd;display:flex;justify-content:space-between;align-items:center">
            <h2 id="btg-modal-title" style="margin:0">Add Meeting</h2>
            <button type="button" class="btg-close" style="background:none;border:none;font-size:20px;cursor:pointer">&times;</button>
        </div>
        <form id="btg-meeting-form" style="padding:20px">
            <input type="hidden" name="meeting_id" id="f-meeting-id">
            <div style="display:grid;gap:12px">
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Title*</label>
                <input type="text" name="title" id="f-title" required class="regular-text" style="width:100%" placeholder="e.g. General Assembly"></div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Date*</label>
                <input type="date" name="meeting_date" id="f-date" required class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Type</label>
                <select name="meeting_type" id="f-type" style="width:100%">
                    <option value="general">General Assembly</option>
                    <option value="board">Board Meeting</option>
                    <option value="special">Special Meeting</option>
                    <option value="budget">Budget Hearing</option>
                </select></div>
                </div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Location</label>
                <input type="text" name="location" id="f-location" class="regular-text" style="width:100%" placeholder="e.g. Clubhouse"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Notes</label>
                <textarea name="notes" id="f-notes" rows="3" class="regular-text" style="width:100%"></textarea></div>
            </div>
            <div style="margin-top:20px;text-align:right">
                <button type="button" class="button btg-close">Cancel</button>
                <button type="submit" class="button button-primary" style="margin-left:8px">Save Meeting</button>
            </div>
        </form>
    </div></div>
    <div id="btg-attend-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);z-index:100000">
    <div style="background:#fff;width:700px;margin:60px auto;border-radius:8px;padding:0;max-height:80vh;display:flex;flex-direction:column">
        <div style="padding:15px 20px;border-bottom:1px solid #ddd;display:flex;justify-content:space-between;align-items:center">
            <h2 id="btg-attend-title" style="margin:0">Attendance</h2>
            <button type="button" class="btg-close-attend" style="background:none;border:none;font-size:20px;cursor:pointer">&times;</button>
        </div>
        <div style="padding:20px;overflow-y:auto" id="btg-attend-list">Loading...</div>
    </div></div>
    <script>
    jQuery(function($){
        function load(){
            $.post(ajaxurl,{action:'btg_crud_meetings',sub:'list'},function(r){
                if(!r.success) return;
                var rows=r.data;
                if(!rows.length){$('#btg-meetings-body').html('<tr><td colspan="5">No meetings recorded yet.</td></tr>');return;}
                var h='';
                rows.forEach(function(m){
                    h+='<tr><td><strong>'+m.meeting_date+'</strong></td>';
                    h+='<td>'+m.title+'</td>';
                    h+='<td>'+m.meeting_type+'</td>';
                    h+='<td><a href="#" class="btg-view-attend" data-id="'+m.meeting_id+'">'+m.attend_count+' attendees</a></td>';
                    h+='<td><a href="#" class="btg-edit-meeting" data-id="'+m.meeting_id+'">Edit</a> | <a href="#" class="btg-del-meeting" data-id="'+m.meeting_id+'" style="color:#a00">Delete</a></td></tr>';
                });
                $('#btg-meetings-body').html(h);
            });
        }
        $('#btg-add-meeting').on('click',function(e){
            e.preventDefault();$('#btg-modal-title').text('Add Meeting');
            $('#btg-meeting-form')[0].reset();$('#f-meeting-id').val('');
            $('#btg-modal').fadeIn(150);
        });
        $(document).on('click','.btg-close',function(){$('#btg-modal').fadeOut(150);});
        $(document).on('click','.btg-close-attend',function(){$('#btg-attend-modal').fadeOut(150);});
        $(document).on('click','.btg-edit-meeting',function(e){
            e.preventDefault();var id=$(this).data('id');
            $.post(ajaxurl,{action:'btg_crud_meetings',sub:'get',meeting_id:id},function(r){
                if(!r.success)return;var m=r.data;
                $('#btg-modal-title').text('Edit Meeting');
                $('#f-meeting-id').val(m.meeting_id);$('#f-title').val(m.title);
                $('#f-date').val(m.meeting_date);$('#f-type').val(m.meeting_type);
                $('#f-location').val(m.location);$('#f-notes').val(m.notes);
                $('#btg-modal').fadeIn(150);
            });
        });
        $(document).on('click','.btg-del-meeting',function(e){
            e.preventDefault();if(!confirm('Delete this meeting and all attendance records?'))return;
            $.post(ajaxurl,{action:'btg_crud_meetings',sub:'delete',meeting_id:$(this).data('id')},function(r){
                if(r.success)load();else alert(r.data||'Error');
            });
        });
        $(document).on('click','.btg-view-attend',function(e){
            e.preventDefault();var id=$(this).data('id');
            $('#btg-attend-title').text('Attendance');
            $.post(ajaxurl,{action:'btg_crud_meetings',sub:'attendance',meeting_id:id},function(r){
                if(!r.success){$('#btg-attend-list').html('Error loading attendance.');return;}
                var rows=r.data;
                if(!rows.length){$('#btg-attend-list').html('No attendance records.');$('#btg-attend-modal').fadeIn(150);return;}
                var h='<table class="wp-list-table widefat fixed striped"><thead><tr><th style="width:100px">Unit</th><th>Attendee 1</th><th>Attendee 2</th></tr></thead><tbody>';
                rows.forEach(function(a){
                    h+='<tr><td><strong>'+(a.building_number?a.building_number+'-':'')+a.unit_number+'</strong></td>';
                    h+='<td>'+a.attendee_name+'</td>';
                    h+='<td>'+(a.attendee_name_2||'\u2014')+'</td></tr>';
                });
                h+='</tbody></table><p style="margin-top:10px;color:#666">'+rows.length+' units attended</p>';
                $('#btg-attend-list').html(h);
                $('#btg-attend-modal').fadeIn(150);
            });
        });
        $('#btg-meeting-form').on('submit',function(e){
            e.preventDefault();var d=$(this).serializeArray();
            d.push({name:'action',value:'btg_crud_meetings'},{name:'sub',value:'save'});
            $.post(ajaxurl,$.param(d),function(r){
                if(r.success){$('#btg-modal').fadeOut(150);load();}else alert(r.data||'Error');
            });
        });
        load();
    });
    </script>
    <?php
}

function btg_render_documents() {
    global $wpdb;
    btg_ensure_documents_table();
    $p = $wpdb->prefix . "btg_";
    ?>
    <div class="wrap">
    <h1>Documents <a href="#" class="page-title-action" id="btg-add-doc">Upload New</a></h1>
    <p>Board documents, forms, and templates \u2014 upload, organize, and download.</p>
    <div style="margin:15px 0;display:flex;gap:10px;align-items:center">
        <select id="btg-cat-filter"><option value="">All Categories</option>
            <option value="form">Forms</option>
            <option value="rules">Rules & Regulations</option>
            <option value="template">Templates</option>
            <option value="minutes">Meeting Minutes</option>
            <option value="financial">Financial</option>
            <option value="general">General</option>
        </select>
        <input type="text" id="btg-doc-search" placeholder="Search documents..." style="width:300px" class="regular-text">
        <span id="btg-doc-count" style="color:#666"></span>
    </div>
    <table class="wp-list-table widefat fixed striped" id="btg-docs-table">
    <thead><tr><th>Title</th><th>Category</th><th>Type</th><th>Size</th><th style="width:70px">Access</th><th>Uploaded</th><th style="width:180px">Actions</th></tr></thead>
    <tbody id="btg-docs-body"><tr><td colspan="6">Loading...</td></tr></tbody>
    </table>
    </div>
    <div id="btg-doc-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);z-index:100000">
    <div style="background:#fff;width:550px;margin:80px auto;border-radius:8px;padding:0">
        <div style="padding:15px 20px;border-bottom:1px solid #ddd;display:flex;justify-content:space-between;align-items:center">
            <h2 id="btg-doc-modal-title" style="margin:0">Upload Document</h2>
            <button type="button" class="btg-close-doc" style="background:none;border:none;font-size:20px;cursor:pointer">&times;</button>
        </div>
        <form id="btg-doc-form" style="padding:20px" enctype="multipart/form-data">
            <input type="hidden" name="document_id" id="fd-id">
            <div style="display:grid;gap:12px">
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Title*</label>
                <input type="text" name="title" id="fd-title" required class="regular-text" style="width:100%"></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Category</label>
                <select name="category" id="fd-category" style="width:100%">
                    <option value="general">General</option>
                    <option value="form">Forms</option>
                    <option value="rules">Rules & Regulations</option>
                    <option value="template">Templates</option>
                    <option value="minutes">Meeting Minutes</option>
                    <option value="financial">Financial</option>
                </select></div>
                <div><label style="font-weight:600;display:block;margin-bottom:4px">Description</label>
                <textarea name="description" id="fd-desc" rows="2" class="regular-text" style="width:100%"></textarea></div>
                <div id="fd-file-wrap"><label style="font-weight:600;display:block;margin-bottom:4px">File*</label>
                <input type="file" name="document_file" id="fd-file" accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.png,.jpg"></div>
                <div><label><input type="checkbox" name="requires_auth" id="fd-auth" value="1"> <strong>Residents Only</strong> — require login to view/download this document</label></div>
            </div>
            <div style="margin-top:20px;text-align:right">
                <button type="button" class="button btg-close-doc">Cancel</button>
                <button type="submit" class="button button-primary" style="margin-left:8px">Upload</button>
            </div>
        </form>
    </div></div>
    <script>
    jQuery(function($){
        var docs=[];
        function fmtSize(b){if(!b)return'\u2014';if(b>1048576)return(b/1048576).toFixed(1)+' MB';return(b/1024).toFixed(0)+' KB';}
        function load(){
            $.post(ajaxurl,{action:'btg_crud_documents',sub:'list'},function(r){
                if(r.success){docs=r.data;render();}
            });
        }
        function render(){
            var cat=$('#btg-cat-filter').val(),s=$('#btg-doc-search').val().toLowerCase(),rows=docs;
            if(cat)rows=rows.filter(function(d){return d.category==cat;});
            if(s)rows=rows.filter(function(d){return(d.title+' '+d.description+' '+d.file_type).toLowerCase().indexOf(s)>=0;});
            $('#btg-doc-count').text(rows.length+' of '+docs.length+' documents');
            if(!rows.length){$('#btg-docs-body').html('<tr><td colspan="7">No documents found.</td></tr>');return;}
            var h='';
            rows.forEach(function(d){
                var auth=d.requires_auth==='1'||d.requires_auth===1;
                h+='<tr><td><strong>'+d.title+'</strong>'+(d.description?'<br><small style="color:#666">'+d.description+'</small>':'')+'</td>';
                h+='<td>'+d.category+'</td>';
                h+='<td>'+d.file_type.toUpperCase()+'</td>';
                h+='<td>'+fmtSize(d.file_size)+'</td>';
                h+='<td>'+(auth?'<span style="color:#E65100" title="Login required">Residents</span>':'<span style="color:#2E7D32">Public</span>')+'</td>';
                h+='<td>'+d.created_at.substring(0,10)+'</td>';
                h+='<td><a href="'+d.file_url+'" target="_blank">Download</a> | <a href="#" class="btg-del-doc" data-id="'+d.document_id+'" style="color:#a00">Delete</a></td></tr>';
            });
            $('#btg-docs-body').html(h);
        }
        $('#btg-cat-filter,#btg-doc-search').on('change keyup',render);
        $('#btg-add-doc').on('click',function(e){
            e.preventDefault();$('#btg-doc-modal-title').text('Upload Document');
            $('#btg-doc-form')[0].reset();$('#fd-id').val('');$('#fd-file-wrap').show();
            $('#btg-doc-modal').fadeIn(150);
        });
        $(document).on('click','.btg-close-doc',function(){$('#btg-doc-modal').fadeOut(150);});
        $(document).on('click','.btg-del-doc',function(e){
            e.preventDefault();if(!confirm('Delete this document?'))return;
            $.post(ajaxurl,{action:'btg_crud_documents',sub:'delete',document_id:$(this).data('id')},function(r){
                if(r.success)load();else alert(r.data||'Error');
            });
        });
        $('#btg-doc-form').on('submit',function(e){
            e.preventDefault();
            var fd=new FormData(this);
            fd.append('action','btg_crud_documents');
            fd.append('sub','save');
            $.ajax({url:ajaxurl,type:'POST',data:fd,processData:false,contentType:false,success:function(r){
                if(r.success){$('#btg-doc-modal').fadeOut(150);load();}else alert(r.data||'Error');
            }});
        });
        load();
    });
    </script>
    <?php
}

function btg_render_email_blast() {
    global $wpdb;
    $p = $wpdb->prefix . "btg_";
    $groups = $wpdb->get_results("SELECT * FROM {$p}email_groups WHERE is_active=1 ORDER BY group_type, group_name", ARRAY_A);
    $logs = $wpdb->get_results("SELECT * FROM {$p}email_log ORDER BY sent_at DESC LIMIT 20", ARRAY_A);
    ?>
    <div class="wrap">
    <h1>Email Blast</h1>
    <p>Send targeted emails to all residents, specific buildings, or custom groups.</p>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:20px;">
        <!-- Compose -->
        <div style="background:#fff;border-radius:8px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);">
            <h2 style="font-size:16px;color:#1B5E20;margin:0 0 16px;">Compose Email</h2>
            <form id="btg-blast-form">
                <div style="margin-bottom:12px"><label style="font-weight:600;display:block;margin-bottom:4px">Recipients*</label>
                <select name="group_id" id="eb-group" required style="width:100%">
                    <option value="">Select group...</option>
                    <?php foreach($groups as $g): ?>
                    <option value="<?php echo $g['group_id']; ?>"><?php echo esc_html($g['group_name']); ?> (<?php echo $g['group_type']; ?>)</option>
                    <?php endforeach; ?>
                    <option value="all">All Residents (owners + renters with email)</option>
                <option value="owners">Owners Only</option>
                <option value="renters">Renters Only</option>
                </select></div>
                <div style="margin-bottom:12px"><label style="font-weight:600;display:block;margin-bottom:4px">Subject*</label>
                <input type="text" name="subject" id="eb-subject" required class="regular-text" style="width:100%" placeholder="e.g. Important Community Notice"></div>
                <div style="margin-bottom:12px"><label style="font-weight:600;display:block;margin-bottom:4px">Message*</label>
                <textarea name="body" id="eb-body" rows="8" required class="regular-text" style="width:100%" placeholder="Type your message here..."></textarea></div>
                <div style="text-align:right">
                    <button type="submit" class="button button-primary" id="eb-send">Send Email Blast</button>
                </div>
                <div id="eb-status" style="margin-top:12px;display:none"></div>
            </form>
        </div>

        <!-- Recent Blasts -->
        <div style="background:#fff;border-radius:8px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);">
            <h2 style="font-size:16px;color:#1B5E20;margin:0 0 16px;">Recent Emails</h2>
            <?php if(empty($logs)): ?>
                <p style="color:#666">No emails sent yet.</p>
            <?php else: ?>
                <table class="widefat striped" style="margin:0">
                <thead><tr><th>Subject</th><th style="width:60px">Sent</th><th style="width:70px">Status</th></tr></thead>
                <tbody>
                <?php foreach($logs as $l): ?>
                <tr>
                    <td><strong><?php echo esc_html($l['subject']); ?></strong><br><small style="color:#666"><?php echo $l['recipient_count']; ?> recipients</small></td>
                    <td><?php echo date('M j', strtotime($l['sent_at'])); ?></td>
                    <td><span style="color:<?php echo $l['status']==='sent'?'#2E7D32':'#C62828'; ?>"><?php echo ucfirst($l['status']); ?></span></td>
                </tr>
                <?php endforeach; ?>
                </tbody></table>
            <?php endif; ?>
        </div>
    </div>
    </div>
    <script>
    jQuery(function($){
        $('#btg-blast-form').on('submit',function(e){
            e.preventDefault();
            if(!confirm('Send this email to the selected group? This cannot be undone.'))return;
            var $btn=$('#eb-send').prop('disabled',true).text('Sending...');
            var d=$(this).serializeArray();
            d.push({name:'action',value:'btg_send_email_blast'});
            $.post(ajaxurl,$.param(d),function(r){
                $btn.prop('disabled',false).text('Send Email Blast');
                if(r.success){
                    $('#eb-status').show().html('<div style="background:#E8F5E9;padding:12px;border-radius:6px;color:#2E7D32"><strong>Sent!</strong> '+r.data+'</div>');
                    $('#btg-blast-form')[0].reset();
                } else {
                    $('#eb-status').show().html('<div style="background:#FFEBEE;padding:12px;border-radius:6px;color:#C62828"><strong>Error:</strong> '+r.data+'</div>');
                }
            });
        });
    });
    </script>
    <?php
}

function btg_render_activity_log() {
    global $wpdb;
    $p = $wpdb->prefix . "btg_";
    ?>
    <div class="wrap">
    <h1>Activity Log</h1>
    <p>Audit trail of all admin actions for accountability.</p>
    <div style="margin:15px 0;display:flex;gap:10px;align-items:center">
        <select id="btg-entity-filter">
            <option value="">All Types</option>
            <option value="owner">Owners</option>
            <option value="renter">Renters</option>
            <option value="parking">Parking</option>
            <option value="board_member">Board Members</option>
            <option value="document">Documents</option>
            <option value="meeting">Meetings</option>
            <option value="email">Emails</option>
        </select>
        <input type="text" id="btg-log-search" placeholder="Search activity..." style="width:300px" class="regular-text">
        <span id="btg-log-count" style="color:#666"></span>
    </div>
    <table class="wp-list-table widefat fixed striped">
    <thead><tr><th style="width:160px">Date</th><th style="width:80px">Action</th><th style="width:100px">Type</th><th>Description</th><th style="width:120px">User</th></tr></thead>
    <tbody id="btg-log-body"><tr><td colspan="5">Loading...</td></tr></tbody>
    </table>
    </div>
    <script>
    jQuery(function($){
        var logs=[];
        function load(){
            $.post(ajaxurl,{action:'btg_crud_activity_log',sub:'list'},function(r){
                if(r.success){logs=r.data;render();}
            });
        }
        function render(){
            var et=$('#btg-entity-filter').val(), s=$('#btg-log-search').val().toLowerCase(), rows=logs;
            if(et) rows=rows.filter(function(l){return l.entity_type===et;});
            if(s) rows=rows.filter(function(l){return(l.description+' '+l.action+' '+l.entity_type+(l.user_login||'')).toLowerCase().indexOf(s)>=0;});
            $('#btg-log-count').text(rows.length+' entries');
            if(!rows.length){$('#btg-log-body').html('<tr><td colspan="5">No activity found.</td></tr>');return;}
            var h='';
            rows.forEach(function(l){
                h+='<tr><td>'+l.created_at+'</td>';
                h+='<td><span style="background:'+(l.action==='create'?'#E8F5E9':l.action==='delete'?'#FFEBEE':'#E3F2FD')+';padding:2px 8px;border-radius:4px;font-size:12px">'+l.action+'</span></td>';
                h+='<td>'+l.entity_type+'</td>';
                h+='<td>'+(l.description||'—')+'</td>';
                h+='<td>'+(l.user_login||'System')+'</td></tr>';
            });
            $('#btg-log-body').html(h);
        }
        $('#btg-entity-filter,#btg-log-search').on('change keyup',render);
        load();
    });
    </script>
    <?php
}

function btg_placeholder_page( $title, $desc ) {
    echo '<div class="wrap">';
    echo '<h1>' . esc_html( $title ) . '</h1>';
    echo '<p>' . esc_html( $desc ) . '</p>';
    echo '<div style="background:#E8F5E9;border-radius:8px;padding:24px;margin-top:20px;text-align:center;">';
    echo '<span class="dashicons dashicons-hammer" style="font-size:48px;color:#2E7D32;"></span>';
    echo '<p style="font-size:16px;color:#2E7D32;font-weight:600;margin-top:12px;">Coming Soon</p>';
    echo '<p style="color:#666;">This section is under active development.</p>';
    echo '</div>';
    echo '</div>';
}

/**
 * ──────────────────────────────────────────────
 *  HELPER: Log activity
 * ──────────────────────────────────────────────
 */
function btg_log_activity( $action, $entity_type, $entity_id = null, $description = '' ) {
    global $wpdb;
    $wpdb->insert(
        $wpdb->prefix . 'btg_activity_log',
        array(
            'user_id'     => get_current_user_id(),
            'action'      => $action,
            'entity_type' => $entity_type,
            'entity_id'   => $entity_id,
            'description' => $description,
            'ip_address'  => isset( $_SERVER['REMOTE_ADDR'] ) ? sanitize_text_field( $_SERVER['REMOTE_ADDR'] ) : '',
        ),
        array( '%d', '%s', '%s', '%d', '%s', '%s' )
    );
}


// AJAX: Owners CRUD
// ============================================
// APPLICATIONS (Rental & Transfer)
// ============================================


function btg_render_applications() {
    ?>
    <div class="wrap btg-applications-wrap">
        <h1 style="margin-bottom:15px;">Applications</h1>

        <!-- ── Tab Navigation ──────────────────────────────────── -->
        <nav class="nav-tab-wrapper btg-app-tabs" style="margin-bottom:20px;">
            <a href="#" class="nav-tab nav-tab-active" data-tab="rental">Rental Applications</a>
            <a href="#" class="nav-tab" data-tab="transfer">Transfer Applications</a>
        </nav>

        <!-- ── Toolbar ─────────────────────────────────────────── -->
        <div style="display:flex; align-items:center; gap:12px; margin-bottom:15px; flex-wrap:wrap;">
            <select id="btg-app-status-filter" style="min-width:140px;">
                <option value="">All Statuses</option>
                <option value="pending">Pending</option>
                <option value="approved">Approved</option>
                <option value="denied">Denied</option>
            </select>
            <input type="text" id="btg-app-search" placeholder="Search..." style="min-width:220px;" />
            <span id="btg-app-count" style="color:#666; font-style:italic;"></span>
        </div>

        <!-- ── Rental Applications Table ───────────────────────── -->
        <div id="btg-tab-rental" class="btg-tab-panel">
            <table class="widefat striped" id="btg-rental-table">
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Applicant</th>
                        <th>Building / Unit</th>
                        <th>Owner</th>
                        <th>Move-in Date</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody></tbody>
            </table>
        </div>

        <!-- ── Transfer Applications Table ─────────────────────── -->
        <div id="btg-tab-transfer" class="btg-tab-panel" style="display:none;">
            <table class="widefat striped" id="btg-transfer-table">
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Current Owner</th>
                        <th>Building / Unit</th>
                        <th>Buyer</th>
                        <th>Closing Date</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody></tbody>
            </table>
        </div>

        <!-- ── View / Edit Modal ───────────────────────────────── -->
        <div id="btg-app-modal-overlay" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:100000;">
            <div id="btg-app-modal" style="
                position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
                background:#fff; border-radius:8px; width:720px; max-width:92vw;
                max-height:85vh; overflow-y:auto; padding:0; z-index:100001;
                box-shadow:0 8px 32px rgba(0,0,0,.3);
            ">
                <div style="display:flex; justify-content:space-between; align-items:center; padding:18px 24px; border-bottom:1px solid #ddd; background:#f9f9f9; border-radius:8px 8px 0 0;">
                    <h2 id="btg-app-modal-title" style="margin:0; font-size:18px; color:#1B5E20;">Application Details</h2>
                    <button type="button" id="btg-app-modal-close" style="background:none; border:none; font-size:22px; cursor:pointer; color:#666; line-height:1;">&times;</button>
                </div>
                <div id="btg-app-modal-body" style="padding:24px;"></div>
            </div>
        </div>
    </div>

    <style>
        .btg-applications-wrap .nav-tab { cursor:pointer; }
        .btg-applications-wrap .nav-tab-active { background:#fff; border-bottom-color:#fff; }
        .btg-app-badge {
            display:inline-block; padding:3px 10px; border-radius:12px;
            font-size:12px; font-weight:600; color:#fff; text-transform:capitalize;
        }
        .btg-app-badge-pending  { background:#E65100; }
        .btg-app-badge-approved { background:#2E7D32; }
        .btg-app-badge-denied   { background:#C62828; }
        .btg-app-detail-grid {
            display:grid; grid-template-columns:1fr 1fr; gap:14px 28px;
        }
        .btg-app-detail-grid .btg-field { margin-bottom:4px; }
        .btg-app-detail-grid .btg-field label {
            display:block; font-weight:600; font-size:12px;
            color:#555; text-transform:uppercase; margin-bottom:2px;
        }
        .btg-app-detail-grid .btg-field span { font-size:14px; color:#222; }
        .btg-app-detail-grid .btg-full { grid-column:1 / -1; }
        .btg-app-actions-row {
            display:flex; gap:10px; justify-content:flex-end;
            padding-top:18px; border-top:1px solid #eee; margin-top:18px;
        }
        .btg-app-actions-row .button-primary {
            background:#2E7D32; border-color:#1B5E20;
        }
        .btg-app-actions-row .button-primary:hover {
            background:#1B5E20;
        }
        #btg-rental-table a.btg-action-link,
        #btg-transfer-table a.btg-action-link {
            cursor:pointer; color:#2E7D32; text-decoration:none; font-weight:500;
        }
        #btg-rental-table a.btg-action-link:hover,
        #btg-transfer-table a.btg-action-link:hover {
            text-decoration:underline; color:#1B5E20;
        }
        .btg-app-sub-text { display:block; font-size:12px; color:#888; }
    </style>

    <script>
    jQuery(function($){

        var currentTab  = 'rental';
        var rentalData  = [];
        var transferData = [];

        // ── Status badge helper ─────────────────────────────────
        function statusBadge(s) {
            var cls = 'btg-app-badge btg-app-badge-' + s;
            return '<span class="' + cls + '">' + s + '</span>';
        }

        // ── Format date helper ──────────────────────────────────
        function fmtDate(d) {
            if (!d) return '—';
            var dt = new Date(d);
            if (isNaN(dt)) return d;
            return dt.toLocaleDateString('en-US', { month:'short', day:'numeric', year:'numeric' });
        }

        function esc(val) {
            if (val === null || typeof val === 'undefined') return '';
            var div = document.createElement('div');
            div.appendChild(document.createTextNode(val));
            return div.innerHTML;
        }

        // ── Load Rental Applications ────────────────────────────
        function loadRental() {
            $.post(ajaxurl, { action:'btg_crud_applications', sub:'list_rental' }, function(r){
                if (!r.success) return;
                rentalData = r.data || [];
                renderRental();
            });
        }

        function renderRental() {
            var filter = $('#btg-app-status-filter').val();
            var search = $('#btg-app-search').val().toLowerCase();
            var rows = rentalData.filter(function(row){
                if (filter && row.status !== filter) return false;
                if (search) {
                    var haystack = [
                        row.applicant_name, row.applicant_email, row.building_number,
                        row.unit_requested, row.owner_name, row.status
                    ].join(' ').toLowerCase();
                    if (haystack.indexOf(search) === -1) return false;
                }
                return true;
            });

            var html = '';
            if (rows.length === 0) {
                html = '<tr><td colspan="7" style="text-align:center;color:#999;padding:20px;">No rental applications found.</td></tr>';
            } else {
                $.each(rows, function(i, r){
                    html += '<tr>'
                        + '<td>' + esc(fmtDate(r.submitted_at)) + '</td>'
                        + '<td>' + esc(r.applicant_name) + (r.applicant_email ? '<span class="btg-app-sub-text">' + esc(r.applicant_email) + '</span>' : '') + '</td>'
                        + '<td>' + esc(r.building_number) + ' / ' + esc(r.unit_requested) + '</td>'
                        + '<td>' + esc(r.owner_name || '—') + '</td>'
                        + '<td>' + esc(fmtDate(r.move_in_date)) + '</td>'
                        + '<td>' + statusBadge(r.status) + '</td>'
                        + '<td>'
                        +   '<a class="btg-action-link" onclick="btgAppView(' + r.app_id + ',\'rental\')">View</a>'
                        +   ' | '
                        +   '<a class="btg-action-link" onclick="btgAppView(' + r.app_id + ',\'rental\')">Update Status</a>'
                        + '</td>'
                        + '</tr>';
                });
            }
            $('#btg-rental-table tbody').html(html);
            updateCount(rows.length);
        }

        // ── Load Transfer Applications ──────────────────────────
        function loadTransfer() {
            $.post(ajaxurl, { action:'btg_crud_applications', sub:'list_transfer' }, function(r){
                if (!r.success) return;
                transferData = r.data || [];
                renderTransfer();
            });
        }

        function renderTransfer() {
            var filter = $('#btg-app-status-filter').val();
            var search = $('#btg-app-search').val().toLowerCase();
            var rows = transferData.filter(function(row){
                if (filter && row.status !== filter) return false;
                if (search) {
                    var haystack = [
                        row.current_owner, row.buyer_name, row.buyer_email,
                        row.building_number, row.unit_number, row.status
                    ].join(' ').toLowerCase();
                    if (haystack.indexOf(search) === -1) return false;
                }
                return true;
            });

            var html = '';
            if (rows.length === 0) {
                html = '<tr><td colspan="7" style="text-align:center;color:#999;padding:20px;">No transfer applications found.</td></tr>';
            } else {
                $.each(rows, function(i, r){
                    html += '<tr>'
                        + '<td>' + esc(fmtDate(r.submitted_at)) + '</td>'
                        + '<td>' + esc(r.current_owner) + '</td>'
                        + '<td>' + esc(r.building_number) + ' / ' + esc(r.unit_number) + '</td>'
                        + '<td>' + esc(r.buyer_name) + (r.buyer_email ? '<span class="btg-app-sub-text">' + esc(r.buyer_email) + '</span>' : '') + '</td>'
                        + '<td>' + esc(fmtDate(r.closing_date)) + '</td>'
                        + '<td>' + statusBadge(r.status) + '</td>'
                        + '<td>'
                        +   '<a class="btg-action-link" onclick="btgAppView(' + r.app_id + ',\'transfer\')">View</a>'
                        +   ' | '
                        +   '<a class="btg-action-link" onclick="btgAppView(' + r.app_id + ',\'transfer\')">Update Status</a>'
                        + '</td>'
                        + '</tr>';
                });
            }
            $('#btg-transfer-table tbody').html(html);
            updateCount(rows.length);
        }

        function updateCount(n) {
            var label = currentTab === 'rental' ? 'rental' : 'transfer';
            $('#btg-app-count').text(n + ' ' + label + ' application' + (n !== 1 ? 's' : ''));
        }

        // ── Tab Switching ───────────────────────────────────────
        $('.btg-app-tabs .nav-tab').on('click', function(e){
            e.preventDefault();
            $('.btg-app-tabs .nav-tab').removeClass('nav-tab-active');
            $(this).addClass('nav-tab-active');
            currentTab = $(this).data('tab');

            // Reset filters on tab switch
            $('#btg-app-status-filter').val('');
            $('#btg-app-search').val('');

            if (currentTab === 'rental') {
                $('#btg-tab-rental').show();
                $('#btg-tab-transfer').hide();
                loadRental();
            } else {
                $('#btg-tab-rental').hide();
                $('#btg-tab-transfer').show();
                loadTransfer();
            }
        });

        // ── Filter / Search ─────────────────────────────────────
        $('#btg-app-status-filter').on('change', function(){
            if (currentTab === 'rental') renderRental();
            else renderTransfer();
        });

        var searchTimer;
        $('#btg-app-search').on('keyup', function(){
            clearTimeout(searchTimer);
            searchTimer = setTimeout(function(){
                if (currentTab === 'rental') renderRental();
                else renderTransfer();
            }, 250);
        });

        // ── View Application (global) ───────────────────────────
        window.btgAppView = function(appId, type) {
            $.post(ajaxurl, { action:'btg_crud_applications', sub:'view', app_id:appId, type:type }, function(r){
                if (!r.success) { alert('Error loading application.'); return; }
                var d = r.data;
                var html = '<div class="btg-app-detail-grid">';

                if (type === 'rental') {
                    html += field('Applicant Name', d.applicant_name);
                    html += field('Email', d.applicant_email);
                    html += field('Phone', d.applicant_phone);
                    html += field('Building', d.building_number);
                    html += field('Unit Requested', d.unit_requested);
                    html += field('Owner', d.owner_name);
                    html += field('Move-in Date', fmtDate(d.move_in_date));
                    html += field('Lease Term', d.lease_term);
                    html += field('Occupants', d.num_occupants);
                    html += field('Has Pets', d.has_pets == 1 ? 'Yes' : 'No');
                    if (d.pet_details) html += field('Pet Details', d.pet_details, true);
                    if (d.vehicles) html += field('Vehicles', d.vehicles, true);
                    if (d.additional_notes) html += field('Additional Notes', d.additional_notes, true);
                    html += field('Submitted', fmtDate(d.submitted_at));
                    html += field('Current Status', statusBadge(d.status));
                    if (d.reviewer_name) {
                        html += field('Reviewed By', d.reviewer_name);
                        html += field('Reviewed At', fmtDate(d.reviewed_at));
                    }
                } else {
                    html += field('Current Owner', d.current_owner);
                    html += field('Building', d.building_number);
                    html += field('Unit', d.unit_number);
                    html += field('Buyer Name', d.buyer_name);
                    html += field('Buyer Email', d.buyer_email);
                    html += field('Buyer Phone', d.buyer_phone);
                    html += field('Closing Date', fmtDate(d.closing_date));
                    html += field('Title Company', d.title_company);
                    html += field('Realtor Name', d.realtor_name);
                    html += field('Realtor Phone', d.realtor_phone);
                    if (d.additional_notes) html += field('Additional Notes', d.additional_notes, true);
                    html += field('Submitted', fmtDate(d.submitted_at));
                    html += field('Current Status', statusBadge(d.status));
                    if (d.reviewer_name) {
                        html += field('Reviewed By', d.reviewer_name);
                        html += field('Reviewed At', fmtDate(d.reviewed_at));
                    }
                }

                html += '</div>';

                // ── Admin Controls ──────────────────────────────
                html += '<div style="margin-top:22px; padding-top:18px; border-top:1px solid #eee;">';
                html += '<div style="display:grid; grid-template-columns:1fr 1fr; gap:14px 28px;">';

                html += '<div class="btg-field">';
                html += '<label for="btg-app-status-select">Update Status</label>';
                html += '<select id="btg-app-status-select" style="width:100%;">';
                html += '<option value="pending"'  + (d.status==='pending'  ? ' selected' : '') + '>Pending</option>';
                html += '<option value="approved"'  + (d.status==='approved' ? ' selected' : '') + '>Approved</option>';
                html += '<option value="denied"'    + (d.status==='denied'   ? ' selected' : '') + '>Denied</option>';
                html += '</select>';
                html += '</div>';

                html += '<div></div>'; // spacer

                html += '<div class="btg-field btg-full">';
                html += '<label for="btg-app-admin-notes">Admin Notes</label>';
                html += '<textarea id="btg-app-admin-notes" rows="3" style="width:100%;">' + esc(d.admin_notes || '') + '</textarea>';
                html += '</div>';

                html += '</div>'; // grid
                html += '</div>'; // controls wrapper

                // ── Action Buttons ──────────────────────────────
                html += '<div class="btg-app-actions-row">';
                html += '<button type="button" class="button" id="btg-app-modal-cancel">Close</button>';
                html += '<button type="button" class="button button-primary" id="btg-app-save-status" '
                     +  'data-id="' + d.app_id + '" data-type="' + type + '">Save Changes</button>';
                html += '</div>';

                var titleLabel = type === 'rental' ? 'Rental Application' : 'Transfer Application';
                $('#btg-app-modal-title').text(titleLabel + ' #' + d.app_id);
                $('#btg-app-modal-body').html(html);
                $('#btg-app-modal-overlay').fadeIn(150);
            });
        };

        function field(label, value, full) {
            var cls = 'btg-field' + (full ? ' btg-full' : '');
            var val = (value !== null && typeof value !== 'undefined' && value !== '') ? value : '—';
            return '<div class="' + cls + '"><label>' + esc(label) + '</label><span>' + val + '</span></div>';
        }

        // ── Save Status ─────────────────────────────────────────
        $(document).on('click', '#btg-app-save-status', function(){
            var btn    = $(this);
            var appId  = btn.data('id');
            var type   = btn.data('type');
            var status = $('#btg-app-status-select').val();
            var notes  = $('#btg-app-admin-notes').val();

            btn.prop('disabled', true).text('Saving...');

            $.post(ajaxurl, {
                action:      'btg_crud_applications',
                sub:         'update_status',
                app_id:      appId,
                type:        type,
                status:      status,
                admin_notes: notes
            }, function(r){
                btn.prop('disabled', false).text('Save Changes');
                if (r.success) {
                    $('#btg-app-modal-overlay').fadeOut(150);
                    if (currentTab === 'rental') loadRental();
                    else loadTransfer();
                } else {
                    alert('Error: ' + (r.data || 'Could not update status.'));
                }
            });
        });

        // ── Close Modal ─────────────────────────────────────────
        $(document).on('click', '#btg-app-modal-close, #btg-app-modal-cancel', function(){
            $('#btg-app-modal-overlay').fadeOut(150);
        });
        $('#btg-app-modal-overlay').on('click', function(e){
            if (e.target === this) $(this).fadeOut(150);
        });

        // ── Initial Load ────────────────────────────────────────
        loadRental();
    });
    </script>
    <?php
}


add_action("wp_ajax_btg_crud_owners", function(){
    if(!current_user_can("manage_btg")) wp_send_json_error("Unauthorized");
    global $wpdb; $p=$wpdb->prefix."btg_"; $sub=$_POST["sub"]??"";
    if($sub==="list"){
        $rows=$wpdb->get_results("SELECT o.*, u.unit_number, b.building_number FROM {$p}owners o JOIN {$p}units u ON o.unit_id=u.unit_id JOIN {$p}buildings b ON u.building_id=b.building_id ORDER BY b.building_number+0, u.unit_number+0, o.is_primary_resident DESC", ARRAY_A);
        wp_send_json_success($rows);
    }
    if($sub==="save"){
        $bn=intval($_POST["building_number"]); $un=intval($_POST["unit_number"]);
        $bid=$wpdb->get_var($wpdb->prepare("SELECT building_id FROM {$p}buildings WHERE building_number=%d",$bn));
        if(!$bid) wp_send_json_error("Building not found");
        $uid=$wpdb->get_var($wpdb->prepare("SELECT unit_id FROM {$p}units WHERE building_id=%d AND unit_number=%d",$bid,$un));
        if(!$uid) wp_send_json_error("Unit $bn-$un not found");
        $data=array("unit_id"=>$uid,"first_name"=>sanitize_text_field($_POST["first_name"]),"last_name"=>sanitize_text_field($_POST["last_name"]),"email"=>sanitize_email($_POST["email"]??""),"phone"=>sanitize_text_field($_POST["phone"]??""),"is_primary_resident"=>isset($_POST["is_primary"])?intval($_POST["is_primary"]):1,"is_active"=>1);
        $oid=intval($_POST["owner_id"]??"0");
        if($oid){$wpdb->update("{$p}owners",$data,array("owner_id"=>$oid));wp_send_json_success("updated");}
        else{$wpdb->insert("{$p}owners",$data);wp_send_json_success("inserted");}
    }
    if($sub==="delete"){
        $oid=intval($_POST["owner_id"]??0);
        if($oid) $wpdb->delete("{$p}owners",array("owner_id"=>$oid));
        wp_send_json_success("deleted");
    }
    wp_send_json_error("Invalid sub-action");
});

// AJAX: Renters CRUD
add_action("wp_ajax_btg_crud_renters", function(){
    if(!current_user_can("manage_btg")) wp_send_json_error("Unauthorized");
    global $wpdb; $p=$wpdb->prefix."btg_"; $sub=$_POST["sub"]??"";
    if($sub==="list"){
        $rows=$wpdb->get_results("SELECT r.*, u.unit_number, b.building_number FROM {$p}renters r JOIN {$p}units u ON r.unit_id=u.unit_id JOIN {$p}buildings b ON u.building_id=b.building_id ORDER BY b.building_number+0, u.unit_number+0", ARRAY_A);
        wp_send_json_success($rows);
    }
    if($sub==="save"){
        $bn=intval($_POST["building_number"]); $un=intval($_POST["unit_number"]);
        $bid=$wpdb->get_var($wpdb->prepare("SELECT building_id FROM {$p}buildings WHERE building_number=%d",$bn));
        if(!$bid) wp_send_json_error("Building not found");
        $uid=$wpdb->get_var($wpdb->prepare("SELECT unit_id FROM {$p}units WHERE building_id=%d AND unit_number=%d",$bid,$un));
        if(!$uid) wp_send_json_error("Unit $bn-$un not found");
        $data=array("unit_id"=>$uid,"first_name"=>sanitize_text_field($_POST["first_name"]),"last_name"=>sanitize_text_field($_POST["last_name"]),"email"=>sanitize_email($_POST["email"]??""),"phone"=>sanitize_text_field($_POST["phone"]??""),"is_active"=>1);
        $rid=intval($_POST["renter_id"]??"0");
        if($rid){$wpdb->update("{$p}renters",$data,array("renter_id"=>$rid));wp_send_json_success("updated");}
        else{$wpdb->insert("{$p}renters",$data);wp_send_json_success("inserted");}
    }
    if($sub==="delete"){
        $rid=intval($_POST["renter_id"]??0);
        if($rid) $wpdb->delete("{$p}renters",array("renter_id"=>$rid));
        wp_send_json_success("deleted");
    }
    wp_send_json_error("Invalid sub-action");
});

// AJAX: Parking Permits CRUD
add_action("wp_ajax_btg_crud_permits", function(){
    if(!current_user_can("manage_btg")) wp_send_json_error("Unauthorized");
    global $wpdb; $p=$wpdb->prefix."btg_"; $sub=$_POST["sub"]??"";
    if($sub==="list"){
        $rows=$wpdb->get_results("SELECT pp.*, u.unit_number, b.building_number FROM {$p}parking_permits pp JOIN {$p}units u ON pp.unit_id=u.unit_id JOIN {$p}buildings b ON u.building_id=b.building_id ORDER BY b.building_number+0, u.unit_number+0, pp.resident_name", ARRAY_A);
        wp_send_json_success($rows);
    }
    if($sub==="save"){
        $bn=intval($_POST["building_number"]); $un=intval($_POST["unit_number"]);
        $bid=$wpdb->get_var($wpdb->prepare("SELECT building_id FROM {$p}buildings WHERE building_number=%d",$bn));
        if(!$bid) wp_send_json_error("Building not found");
        $uid=$wpdb->get_var($wpdb->prepare("SELECT unit_id FROM {$p}units WHERE building_id=%d AND unit_number=%d",$bid,$un));
        if(!$uid) wp_send_json_error("Unit $bn-$un not found");
        $data=array("unit_id"=>$uid,"resident_name"=>sanitize_text_field($_POST["resident_name"]),"resident_type"=>sanitize_text_field($_POST["resident_type"]??"owner"),"vehicle_make"=>sanitize_text_field($_POST["vehicle_make"]??""),"vehicle_model"=>sanitize_text_field($_POST["vehicle_model"]??""),"vehicle_color"=>sanitize_text_field($_POST["vehicle_color"]??""),"license_plate"=>strtoupper(sanitize_text_field($_POST["license_plate"]??"")),"permit_number"=>sanitize_text_field($_POST["permit_number"]??""),"status"=>"active");
        $pid=intval($_POST["permit_id"]??"0");
        if($pid){$wpdb->update("{$p}parking_permits",$data,array("permit_id"=>$pid));wp_send_json_success("updated");}
        else{$wpdb->insert("{$p}parking_permits",$data);wp_send_json_success("inserted");}
    }
    if($sub==="delete"){
        $pid=intval($_POST["permit_id"]??0);
        if($pid) $wpdb->delete("{$p}parking_permits",array("permit_id"=>$pid));
        wp_send_json_success("deleted");
    }
    wp_send_json_error("Invalid sub-action");
});
// AJAX: Board Members CRUD
add_action("wp_ajax_btg_crud_board", function(){
    if(!current_user_can("manage_btg")) wp_send_json_error("Unauthorized");
    global $wpdb; $p=$wpdb->prefix."btg_"; $sub=$_POST["sub"]??"";
    if($sub==="list"){
        $rows=$wpdb->get_results("SELECT * FROM {$p}board_members ORDER BY is_active DESC, display_order ASC, full_name ASC", ARRAY_A);
        wp_send_json_success($rows);
    }
    if($sub==="save"){
        $data=array(
            "full_name"=>sanitize_text_field($_POST["full_name"]),
            "title"=>sanitize_text_field($_POST["title"]),
            "contact_email"=>sanitize_email($_POST["contact_email"]??""),
            "building_number"=>sanitize_text_field($_POST["building_number"]??""),
            "term_start"=>sanitize_text_field($_POST["term_start"]??"")?:null,
            "term_end"=>sanitize_text_field($_POST["term_end"]??"")?:null,
            "committees"=>sanitize_text_field($_POST["committees"]??""),
            "bio"=>sanitize_textarea_field($_POST["bio"]??""),
            "display_order"=>intval($_POST["display_order"]??0),
            "is_active"=>isset($_POST["is_active"])?intval($_POST["is_active"]):0,
        );
        $mid=intval($_POST["member_id"]??"0");
        if($mid){
            $wpdb->update("{$p}board_members",$data,array("member_id"=>$mid));
            btg_log_activity("update","board_member",$mid,"Updated board member: ".$data["full_name"]);
            wp_send_json_success("updated");
        } else {
            $wpdb->insert("{$p}board_members",$data);
            $new_id=$wpdb->insert_id;
            btg_log_activity("create","board_member",$new_id,"Added board member: ".$data["full_name"]);
            wp_send_json_success("inserted");
        }
    }
    if($sub==="delete"){
        $mid=intval($_POST["member_id"]??0);
        if($mid){
            $name=$wpdb->get_var($wpdb->prepare("SELECT full_name FROM {$p}board_members WHERE member_id=%d",$mid));
            $wpdb->delete("{$p}board_members",array("member_id"=>$mid));
            btg_log_activity("delete","board_member",$mid,"Deleted board member: ".($name??"unknown"));
        }
        wp_send_json_success("deleted");
    }
    wp_send_json_error("Invalid sub-action");
});

// AJAX: Applications CRUD

add_action( "wp_ajax_btg_crud_applications", function () {
    if ( ! current_user_can( "manage_btg" ) ) {
        wp_send_json_error( "Unauthorized" );
    }

    global $wpdb;
    $p   = $wpdb->prefix . "btg_";
    $sub = isset( $_POST["sub"] ) ? sanitize_text_field( $_POST["sub"] ) : "";

    // ── List Rental Applications ────────────────────────────────────
    if ( $sub === "list_rental" ) {
        $rows = $wpdb->get_results( "SELECT * FROM {$p}rental_applications ORDER BY submitted_at DESC" );
        wp_send_json_success( $rows );
    }

    // ── List Transfer Applications ──────────────────────────────────
    if ( $sub === "list_transfer" ) {
        $rows = $wpdb->get_results( "SELECT * FROM {$p}transfer_applications ORDER BY submitted_at DESC" );
        wp_send_json_success( $rows );
    }

    // ── View Single Application ─────────────────────────────────────
    if ( $sub === "view" ) {
        $app_id = absint( $_POST["app_id"] ?? 0 );
        $type   = sanitize_text_field( $_POST["type"] ?? "" );

        if ( ! $app_id || ! in_array( $type, array( "rental", "transfer" ), true ) ) {
            wp_send_json_error( "Invalid parameters" );
        }

        $table = ( $type === "rental" ) ? "{$p}rental_applications" : "{$p}transfer_applications";
        $row   = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE app_id = %d", $app_id ) );

        if ( ! $row ) {
            wp_send_json_error( "Application not found" );
        }

        // Attach reviewer display name if available
        if ( ! empty( $row->reviewed_by ) ) {
            $reviewer        = get_userdata( $row->reviewed_by );
            $row->reviewer_name = $reviewer ? $reviewer->display_name : "Unknown";
        } else {
            $row->reviewer_name = "";
        }

        wp_send_json_success( $row );
    }

    // ── Update Status ───────────────────────────────────────────────
    if ( $sub === "update_status" ) {
        $app_id      = absint( $_POST["app_id"] ?? 0 );
        $type        = sanitize_text_field( $_POST["type"] ?? "" );
        $new_status  = sanitize_text_field( $_POST["status"] ?? "" );
        $admin_notes = sanitize_textarea_field( $_POST["admin_notes"] ?? "" );

        if ( ! $app_id || ! in_array( $type, array( "rental", "transfer" ), true ) ) {
            wp_send_json_error( "Invalid parameters" );
        }
        if ( ! in_array( $new_status, array( "pending", "approved", "denied" ), true ) ) {
            wp_send_json_error( "Invalid status" );
        }

        $table = ( $type === "rental" ) ? "{$p}rental_applications" : "{$p}transfer_applications";

        $updated = $wpdb->update(
            $table,
            array(
                "status"      => $new_status,
                "reviewed_by" => get_current_user_id(),
                "reviewed_at" => current_time( "mysql" ),
                "admin_notes" => $admin_notes,
            ),
            array( "app_id" => $app_id ),
            array( "%s", "%d", "%s", "%s" ),
            array( "%d" )
        );

        if ( $updated === false ) {
            wp_send_json_error( "Database update failed" );
        }

        $label = ( $type === "rental" ) ? "Rental Application" : "Transfer Application";
        btg_log_activity(
            "update_status",
            "{$type}_application",
            $app_id,
            sprintf( "%s #%d status changed to %s", $label, $app_id, $new_status )
        );

        wp_send_json_success( "Status updated" );
    }

    // ── Delete Application ──────────────────────────────────────────
    if ( $sub === "delete" ) {
        $app_id = absint( $_POST["app_id"] ?? 0 );
        $type   = sanitize_text_field( $_POST["type"] ?? "" );

        if ( ! $app_id || ! in_array( $type, array( "rental", "transfer" ), true ) ) {
            wp_send_json_error( "Invalid parameters" );
        }

        $table = ( $type === "rental" ) ? "{$p}rental_applications" : "{$p}transfer_applications";

        $deleted = $wpdb->delete( $table, array( "app_id" => $app_id ), array( "%d" ) );

        if ( $deleted === false ) {
            wp_send_json_error( "Database delete failed" );
        }

        $label = ( $type === "rental" ) ? "Rental Application" : "Transfer Application";
        btg_log_activity(
            "delete",
            "{$type}_application",
            $app_id,
            sprintf( "%s #%d deleted", $label, $app_id )
        );

        wp_send_json_success( "Deleted" );
    }

    wp_send_json_error( "Unknown sub-action" );
});

// AJAX: Meetings CRUD
add_action("wp_ajax_btg_crud_meetings", function(){
    if(!current_user_can("manage_btg")) wp_send_json_error("Unauthorized");
    global $wpdb; $p=$wpdb->prefix."btg_"; $sub=$_POST["sub"]??"";
    btg_ensure_meeting_tables();
    if($sub==="list"){
        $rows=$wpdb->get_results("SELECT m.*, (SELECT COUNT(*) FROM {$p}meeting_attendance WHERE meeting_id=m.meeting_id) as attend_count FROM {$p}meetings m ORDER BY m.meeting_date DESC", ARRAY_A);
        wp_send_json_success($rows);
    }
    if($sub==="get"){
        $mid=intval($_POST["meeting_id"]??0);
        $row=$wpdb->get_row($wpdb->prepare("SELECT * FROM {$p}meetings WHERE meeting_id=%d",$mid), ARRAY_A);
        wp_send_json_success($row);
    }
    if($sub==="save"){
        $data=array("title"=>sanitize_text_field($_POST["title"]),"meeting_date"=>sanitize_text_field($_POST["meeting_date"]),"meeting_type"=>sanitize_text_field($_POST["meeting_type"]??"general"),"location"=>sanitize_text_field($_POST["location"]??""),"notes"=>sanitize_textarea_field($_POST["notes"]??""));
        $mid=intval($_POST["meeting_id"]??"0");
        if($mid){$wpdb->update("{$p}meetings",$data,array("meeting_id"=>$mid));wp_send_json_success("updated");}
        else{$wpdb->insert("{$p}meetings",$data);wp_send_json_success("inserted");}
    }
    if($sub==="delete"){
        $mid=intval($_POST["meeting_id"]??0);
        if($mid){$wpdb->delete("{$p}meeting_attendance",array("meeting_id"=>$mid));$wpdb->delete("{$p}meetings",array("meeting_id"=>$mid));}
        wp_send_json_success("deleted");
    }
    if($sub==="attendance"){
        $mid=intval($_POST["meeting_id"]??0);
        $rows=$wpdb->get_results($wpdb->prepare("SELECT a.*, u.unit_number, b.building_number FROM {$p}meeting_attendance a LEFT JOIN {$p}units u ON a.unit_id=u.unit_id LEFT JOIN {$p}buildings b ON u.building_id=b.building_id WHERE a.meeting_id=%d ORDER BY b.building_number+0, u.unit_number+0",$mid), ARRAY_A);
        wp_send_json_success($rows);
    }
    wp_send_json_error("Invalid sub-action");
});

// AJAX: Documents CRUD
add_action("wp_ajax_btg_crud_documents", function(){
    if(!current_user_can("manage_btg")) wp_send_json_error("Unauthorized");
    global $wpdb; $p=$wpdb->prefix."btg_"; $sub=$_POST["sub"]??"";
    btg_ensure_documents_table();
    if($sub==="list"){
        $rows=$wpdb->get_results("SELECT * FROM {$p}documents WHERE is_active=1 ORDER BY created_at DESC", ARRAY_A);
        wp_send_json_success($rows);
    }
    if($sub==="save"){
        if(!empty($_FILES["document_file"]["name"])){
            $upload_dir=wp_upload_dir();
            $btg_dir=$upload_dir["basedir"]."/btg-documents";
            if(!file_exists($btg_dir)) wp_mkdir_p($btg_dir);
            $filename=sanitize_file_name($_FILES["document_file"]["name"]);
            $dest=$btg_dir."/".$filename;
            if(file_exists($dest)) $filename=time()."_".$filename;
            $dest=$btg_dir."/".$filename;
            if(!move_uploaded_file($_FILES["document_file"]["tmp_name"],$dest)) wp_send_json_error("Upload failed");
            $url=$upload_dir["baseurl"]."/btg-documents/".$filename;
            $ext=strtolower(pathinfo($filename,PATHINFO_EXTENSION));
            $data=array("title"=>sanitize_text_field($_POST["title"]),"description"=>sanitize_textarea_field($_POST["description"]??""),"file_path"=>$dest,"file_url"=>$url,"file_type"=>$ext,"file_size"=>filesize($dest),"category"=>sanitize_text_field($_POST["category"]??"general"),"requires_auth"=>isset($_POST["requires_auth"])?intval($_POST["requires_auth"]):0,"uploaded_by"=>get_current_user_id(),"is_active"=>1);
            $wpdb->insert("{$p}documents",$data);
            wp_send_json_success("uploaded");
        }
        wp_send_json_error("No file provided");
    }
    if($sub==="delete"){
        $did=intval($_POST["document_id"]??0);
        if($did){
            $doc=$wpdb->get_row($wpdb->prepare("SELECT file_path FROM {$p}documents WHERE document_id=%d",$did));
            if($doc && file_exists($doc->file_path)) @unlink($doc->file_path);
            $wpdb->delete("{$p}documents",array("document_id"=>$did));
        }
        wp_send_json_success("deleted");
    }
    wp_send_json_error("Invalid sub-action");
});

// AJAX: Email Blast
add_action("wp_ajax_btg_send_email_blast", function(){
    if(!current_user_can("manage_btg")) wp_send_json_error("Unauthorized");
    global $wpdb; $p=$wpdb->prefix."btg_";
    $group_id=$_POST["group_id"]??"";
    $subject=sanitize_text_field($_POST["subject"]??"");
    $body=sanitize_textarea_field($_POST["body"]??"");
    if(!$subject||!$body) wp_send_json_error("Subject and message are required");

    // Gather emails
    $emails=array();
    if($group_id==="owners"||$group_id==="renters"){
        $tbl=($group_id==="owners")?"owners":"renters";
        $emails=$wpdb->get_col("SELECT DISTINCT email FROM {$p}{$tbl} WHERE is_active=1 AND email!='' AND email IS NOT NULL");
    } elseif($group_id==="all"){
        $owners=$wpdb->get_col("SELECT DISTINCT email FROM {$p}owners WHERE is_active=1 AND email!='' AND email IS NOT NULL");
        $renters=$wpdb->get_col("SELECT DISTINCT email FROM {$p}renters WHERE is_active=1 AND email!='' AND email IS NOT NULL");
        $emails=array_unique(array_merge($owners,$renters));
    } else {
        $gid=intval($group_id);
        $group=$wpdb->get_row($wpdb->prepare("SELECT * FROM {$p}email_groups WHERE group_id=%d",$gid),ARRAY_A);
        if(!$group) wp_send_json_error("Group not found");
        if($group["group_type"]==="all"){
            $owners=$wpdb->get_col("SELECT DISTINCT email FROM {$p}owners WHERE is_active=1 AND email!='' AND email IS NOT NULL");
            $renters=$wpdb->get_col("SELECT DISTINCT email FROM {$p}renters WHERE is_active=1 AND email!='' AND email IS NOT NULL");
            $emails=array_unique(array_merge($owners,$renters));
        } elseif($group["group_type"]==="building" && $group["building_id"]){
            $bid=$group["building_id"];
            $owners=$wpdb->get_col($wpdb->prepare("SELECT DISTINCT o.email FROM {$p}owners o JOIN {$p}units u ON o.unit_id=u.unit_id WHERE u.building_id=%d AND o.is_active=1 AND o.email!='' AND o.email IS NOT NULL",$bid));
            $renters=$wpdb->get_col($wpdb->prepare("SELECT DISTINCT r.email FROM {$p}renters r JOIN {$p}units u ON r.unit_id=u.unit_id WHERE u.building_id=%d AND r.is_active=1 AND r.email!='' AND r.email IS NOT NULL",$bid));
            $emails=array_unique(array_merge($owners,$renters));
        } elseif($group["group_type"]==="board"){
            $emails=$wpdb->get_col("SELECT DISTINCT contact_email FROM {$p}board_members WHERE is_active=1 AND contact_email!='' AND contact_email IS NOT NULL");
        }
    }
    $emails=array_filter($emails);
    if(empty($emails)) wp_send_json_error("No email addresses found for this group");

    // Send
    $from_name=get_bloginfo("name");
    $headers=array("Content-Type: text/plain; charset=UTF-8","From: $from_name <".get_option("admin_email").">");
    $sent=0; $failed=0;
    foreach($emails as $email){
        if(wp_mail($email,$subject,$body,$headers)){$sent++;}else{$failed++;}
    }
    $status=$failed>0?($sent>0?"partial":"failed"):"sent";
    $wpdb->insert("{$p}email_log",array("subject"=>$subject,"body"=>$body,"sent_by"=>get_current_user_id(),"recipient_count"=>$sent,"status"=>$status,"error_message"=>$failed>0?"$failed emails failed":""));
    btg_log_activity("send","email",$wpdb->insert_id,"Email blast: $subject ($sent sent, $failed failed)");
    wp_send_json_success("$sent email(s) sent successfully".($failed?" ($failed failed)":""));
});

// AJAX: Activity Log
add_action("wp_ajax_btg_crud_activity_log", function(){
    if(!current_user_can("manage_btg")) wp_send_json_error("Unauthorized");
    global $wpdb; $p=$wpdb->prefix."btg_"; $sub=$_POST["sub"]??"";
    if($sub==="list"){
        $rows=$wpdb->get_results("SELECT a.*, u.user_login FROM {$p}activity_log a LEFT JOIN {$wpdb->users} u ON a.user_id=u.ID ORDER BY a.created_at DESC LIMIT 200", ARRAY_A);
        wp_send_json_success($rows);
    }
    wp_send_json_error("Invalid sub-action");
});

// One-time attendance import
add_action("wp_ajax_btg_import_attendance", function(){
    if(!current_user_can("manage_btg")) wp_send_json_error("Unauthorized");
    global $wpdb; $p=$wpdb->prefix."btg_";
    btg_ensure_meeting_tables();
    
    // Check if already imported
    $exists=$wpdb->get_var("SELECT meeting_id FROM {$p}meetings WHERE meeting_date='2026-05-03' LIMIT 1");
    if($exists) wp_send_json_error("Meeting 05/03/2026 already imported (ID: $exists)");
    
    // Create the meeting
    $wpdb->insert("{$p}meetings", array("title"=>"General Assembly - Sign In Sheet","meeting_date"=>"2026-05-03","meeting_type"=>"general","location"=>"","notes"=>"Imported from BTGW spreadsheet"));
    $mid=$wpdb->insert_id;
    if(!$mid) wp_send_json_error("Failed to create meeting record");
    
    // Attendance data
    $att=array(array(1,101,'Marcela Duque','Alberto Jose Gomez Zapata'),array(1,102,'Elaine & Peter McMaster',''),array(1,103,'Nicole Dixon',''),array(1,104,'Brunel Petion','Marise Petion'),array(1,105,'Vannessa Khanni',''),array(1,106,'Stacy Darsansingh','Shivanand Darsansingh'),array(1,107,'Cammie & Eric Peterson',''),array(1,108,'Anthony Wright Sr.',''),array(1,109,'Joseph Duhon',''),array(1,110,'Dina Manginelli',''),array(1,111,'Ivette Rius Pena',''),array(1,112,'James Gretschel',''),array(1,113,'June Ciambrone',''),array(1,201,'Delwanda LaShaun Brown',''),array(1,202,'Nicole Jaeger',''),array(1,203,'Sagrario Maria Munoz',''),array(1,204,'Carol B. Abbott Trust',''),array(1,205,'Germina LaGuerre',''),array(1,206,'Rocco Strazza',''),array(1,207,'Matthew Hazel',''),array(1,208,'Ivan Franklin',''),array(1,209,'Genady Mnatsakanian','Janeta Mnatsakanian & Vartan Mnatsakanian'),array(1,210,'John Richards',''),array(1,211,'Rogelio Regalado',''),array(1,212,'Seth Friedson',''),array(2,101,'Anthony Affronti','Mary Affronti'),array(2,102,'Rita Ames',''),array(2,103,'David Wilson',''),array(2,104,'Fedem Marcellus','Marie Kerchie Jean Baptiste'),array(2,105,'Christine Gnanaseelan',''),array(2,106,'Amarante Valery',''),array(2,107,'Claudia Cadavid',''),array(2,108,'Paul & Dawn Perez',''),array(2,201,'Christina & Michael Greschler',''),array(2,202,'Angilene Stewart',''),array(2,203,'Marijose Cardenas Cruz',''),array(2,204,'Vincent Griffin EST',''),array(2,205,'Angela & Jaciel Oliveira',''),array(2,206,'Keyonda Jones',''),array(2,207,'Latonya Lindsey','Gerald Gourdet'),array(2,208,'Adam Manover',''),array(3,101,'James & Amanda Etheridge',''),array(3,102,'David & Veronica Witt','Benttree 102 LLC'),array(3,103,'David Bayardelle',''),array(3,104,'Angela & Carlos Gonzalez',''),array(3,105,'Debbie Spence',''),array(3,106,'Eric & Cammie Peterson',''),array(3,107,'Darci Trachtenberg',''),array(3,108,'Monowar Cunliffe-Steel',''),array(3,201,'Jeane Hah-Garnett',''),array(3,202,'Cindy Roa',''),array(3,203,'Beth Pastorino',''),array(3,204,'Daniel Pritchard',''),array(3,205,'Ermicie Jean Francois',''),array(3,206,'Nurun Begum',''),array(3,207,'Luz Guerrero',''),array(3,208,'Yana Brez','Garik Khechoyan'),array(4,101,'Manuel Romero',''),array(4,102,'James Genna',''),array(4,103,'Ana Leon',''),array(4,104,'RoseAndree Chery','Woodley Jean-Baptiste'),array(4,105,'Stephen Figueira','Vania Boaventura'),array(4,106,'Michelle Carmona Vega',''),array(4,107,'Mary Williamson',''),array(4,108,'Olive Linton',''),array(4,109,'Rumini Peramune',''),array(4,110,'Florraine Saintil',''),array(4,111,'Susan Verbryck',''),array(4,112,'Lucia Merice',''),array(4,201,'Nathan Lowe','Alejandra Rios Franco'),array(4,202,'Laura Acevedo',''),array(4,203,'Verlande Dorilas',''),array(4,204,'Vigen Mnatsakanian','Vigen Mnatsakanian & Vartan Mnatsakanian'),array(4,205,'Vartan Mnatsakanian',''),array(4,206,'Verice Alliance',''),array(4,207,'Lair Hall',''),array(4,208,'Nasser Fakhoury Corniche Tyros, LLC',''),array(4,209,'David & Ermilie Doriscar',''),array(4,210,'Pilar Liza',''),array(4,211,'Jaritza Velazquez',''),array(4,212,'Pasquale Maida',''),array(5,101,'Maria Rosas-Rodriguez','Keith Stevens'),array(5,102,'Jason & Florinda Davis',''),array(5,103,'Susana Sevilla-Ramos','Jose Alvarez'),array(5,104,'Colin & Jeanine Cash',''),array(5,105,'Timothy Riser','Blanca Riser & Allison Roncal'),array(5,106,'Hasnaa Bennani',''),array(5,107,'John Pinto',''),array(5,108,'Michael & Linda Posso',''),array(5,201,'Izmarthe Eristhenes',''),array(5,202,'Nicholas Barlow','Melissa Cajigas'),array(5,203,'Gary and Halina Ngo',''),array(5,204,'Nichole Catanzaro',''),array(5,205,'Frederick & Margarita Russell Jr.',''),array(5,206,'Jean Fortune',''),array(5,207,'Diani Velasquez',''),array(5,208,'Feng Qi Xiao',''),array(6,101,'Monowar Cunliffe-Steel',''),array(6,102,'Daniel Schreiber',''),array(6,103,'Beamish Laura','Beamish Linda M'),array(6,104,'Ernst Azariah Desir',''),array(6,105,'Sharon Steiger',''),array(6,106,'Shereen Cox',''),array(6,107,'Karen Mencarelli','Megan Green'),array(6,108,'Wilson & Marie Emmanuel',''),array(6,109,'Emmanuelle Suarez',''),array(6,110,'Zachary Benach','Thomas Benach & Michele Benach'),array(6,111,'Eric McMahon',''),array(6,112,'Jazz-Lynn Butler',''),array(6,201,'Tania Villegas',''),array(6,202,'Luis & Jennifer Ballesteros',''),array(6,203,'Daniel Schreiber',''),array(6,204,'Hilda Carrera-Tarco','Jose Tarco'),array(6,205,'Natalie McGlashan',''),array(6,206,'Seriah Silcott',''),array(6,207,'Adina Bordei',''),array(6,208,'Andrew Luchey',''),array(6,209,'Angel Lagares',''),array(6,210,'Rechelle Portucela',''),array(6,211,'Rouby Lamy',''),array(6,212,'Stephanie Cradduck',''),array(7,101,'Cindy Francis',''),array(7,102,'Christine Gnanaseelan',''),array(7,103,'Dieuseul Guerrier',''),array(7,104,'Christine Gnanaseelan',''),array(7,105,'Jeremy Garron',''),array(7,106,'Gerald & Zoraya Starner',''),array(7,107,'Angelica Torres','Jhonatan Delgado'),array(7,108,'Juan F Sosa','Yrene Gomez'),array(7,109,'Jagodish and Rina Ray',''),array(7,110,'James & Rebecca Hartman',''),array(7,111,'Eduardo & Susana Nebuloni Rev Tr',''),array(7,112,'John & Phyllis Faraguna',''),array(7,201,'Ramona Moreno','Maribel De Negrette'),array(7,202,'Monserrat Investments LLC','Veronica Ocampo'),array(7,203,'Hector Zupo',''),array(7,204,'Juan Almanza',''),array(7,205,'Monowar Cunliffe-Steel',''),array(7,206,'Lindsay Johnson',''),array(7,207,'Jhohanna Alvarez',''),array(7,208,'Sebastian Felipe Moreno Gomez','Mariam Nicole Cruz Murillo'),array(7,209,'Hasnaa Bennani',''),array(7,210,'Wilber Tovar',''),array(7,211,'Michael Deleeuw',''),array(7,212,'Jeffrey Krzywada',''),array(8,101,'Maude Jerome',''),array(8,102,'Julimar Ribera Laya',''),array(8,103,'Thomas Guerrier',''),array(8,104,'Scott Montgomery',''),array(8,105,'Luz Angela Beard',''),array(8,106,'Ricard Moncion','Lourdy Moncion'),array(8,107,'Carmen Fiestas',''),array(8,108,'Pedro Pena','Ana Pena & Peter Pena'),array(8,109,'Maria Tribble','William Tribble'),array(8,110,'Paola Zamora',''),array(8,111,'Vartan Mnatsakanian, trustee M. Lv.Trust 2/24/20',''),array(8,112,'Maria Olivares',''),array(8,201,'David Wilson',''),array(8,202,'Goretha Fleurantin',''),array(8,203,'Elise Chang','Nerissa Chang /Peta & Suzette Chang'),array(8,204,'Derek Pressley',''),array(8,205,'Elbin Tamariz',''),array(8,206,'Stacey Anderson',''),array(8,207,'Kalum Peramune','Merrilene Peramune'),array(8,208,'Sadat Rizvanolli',''),array(8,209,'Kirk S Holding LLC',''),array(8,210,'Dawn Balliet','Walter Balliet'),array(8,211,'Gabriel Segundo Alquizar Vila','Delia Herrera'),array(8,212,'Geto Dorlizier','Edline Jean-Baptiste'),array(9,101,'Christine Gnanaseelan',''),array(9,102,'Prakashkumar & Ashwini Patel',''),array(9,103,'John & Penni Bulten',''),array(9,104,'Kalpesh & Kejalben Patel',''),array(9,105,'Christopher T Rodriguez',''),array(9,106,'Mario Briceno',''),array(9,107,'Mary Watson',''),array(9,108,'Priscilla Reese',''),array(9,201,'Francesca Panetta',''),array(9,202,'Francesco Ierfino','Katherine Bono'),array(9,203,'Kirielys Mora',''),array(9,204,'Denberwa Berhan',''),array(9,205,'Loretta Gall','John Gall / Millie Gall-Gentilella'),array(9,206,'Gary Boivin',''),array(9,207,'Domenica Tella Trust','Mariano Tella Jr'),array(9,208,'Benet Esterlin',''),array(10,101,'Carolyn Carabetta',''),array(10,102,'Kesha Raymond Arthur Raymond',''),array(10,103,'Rosalind Perez',''),array(10,104,'Alberto Chabusa',''),array(10,105,'Cristina Oleaga ( formerly Russo)',''),array(10,106,'Anthony Lawrence','Heather Mills'),array(10,107,'Nicole Aliste','Dajanel Darris'),array(10,108,'Candida Granger','Joseph Korynsel'),array(10,109,'Andrew Carananti II',''),array(10,110,'Catherine Daley',''),array(10,111,'Patrick Muise','Morgan La Rocca'),array(10,112,'William & Linda Carafa Jr.',''),array(10,201,'Kaushal & Hemlata Desai',''),array(10,202,'Huguens Alexis',''),array(10,203,'Cecilia Virgilio','Virgilio Cuthbert'),array(10,204,'Aminul Azam Shirajee',''),array(10,205,'Louise Gamble',''),array(10,206,'Andre Falcao','Marta Dasilva'),array(10,207,'Beth Shapiro',''),array(10,208,'Clayton & Brittany Welter',''),array(10,209,'Zakirul Shirajee','Jesmin A Aney'),array(10,210,'Donna Dixon-Barnes',''),array(10,211,'Joseph Cote',''),array(10,212,'Garik Khechoyan',''),array(11,101,'Scott Kaplan',''),array(11,102,'Linda Aginian',''),array(11,103,'Caroline Higgins','William Flemm'),array(11,104,'Kyra Wilson Estate',''),array(11,105,'Michael Whyte Jr',''),array(11,106,'Richard Fong',''),array(11,107,'Daniel Arena',''),array(11,108,'Eddy Gutierrez',''),array(11,201,'Vanessa Rodriguez','Alfredo & Nidia Rodriguez'),array(11,202,'Karen Arthur',''),array(11,203,'Crystal Russell',''),array(11,204,'Cesar Ochoa','CEGA 88 LLC CEGA 88 LLC'),array(11,205,'Anthony G Miccio',''),array(11,206,'Lauren Finell',''),array(11,207,'Christopher & Valerie Hyjek',''),array(11,208,'Jose & Nancy Barbalonga',''),array(12,101,'Frantz Derose','Leonise Derose'),array(12,102,'Hasnaa Bennani',''),array(12,103,'Anthony Hannan',''),array(12,104,'Harvene Martin',''),array(12,105,'Julio Martinez','Lilia Buenano'),array(12,106,'Sarrah Morose',''),array(12,107,'Joseph & Jasmin Salami',''),array(12,108,'Carolina Assuncao',''),array(12,201,'Aimee Ortiz-Matos',''),array(12,202,'Kent, Therese and Geordan Ziegler',''),array(12,203,'Mark Skinner',''),array(12,204,'Rico Romero',''),array(12,205,'Mohammed Hossain','Fariha Zaman'),array(12,206,'Daren Baley-Hay',''),array(12,207,'Oyewalle Ojo','Sandra Normil'),array(12,208,'Neil Pertosoff','Suely Pertosof'),array(13,101,'Rafael Nunes Linhares Papa',''),array(13,102,'Mario Cubas',''),array(13,103,'Henry & Eileen McKenzie',''),array(13,104,'Maria Balas',''),array(13,105,'Ari Lewit',''),array(13,106,'Angelina Layne',''),array(13,107,'Michelet Lovinsky','Falonne Lovinsky Vilier'),array(13,108,'Towers & Swan LLC',''),array(13,109,'Edbarda Leon',''),array(13,110,'Tereza Shebbein','Mierielle Shebbein'),array(13,111,'Christoper Wuestman',''),array(13,112,'Claudio Jaffe',''),array(13,201,'Rosemarie Tabio','Alexander Tabio'),array(13,202,'Filomena Gonzalez','Concepcion Schmeda'),array(13,203,'Rafael Nunes Linhares Papa',''),array(13,204,'Michel Belisle','Angela Guigou'),array(13,205,'Gustavo and Juliana Soares Pereira',''),array(13,206,'Charles Martin Rev Tr','Charles & Carolyn Martin Joint Ten'),array(13,207,'Joseph Garconnet','Jeanne Garconnet'),array(13,208,'Yardley Rock',''),array(13,209,'Gina Woods',''),array(13,210,'Howard Storms',''),array(13,211,'Kiara Slaton',''),array(13,212,'Freeman Joseph','Chouloute Aluc'));
    
    $imported=0; $skipped=0;
    foreach($att as $row){
        $bn=$row[0]; $un=$row[1]; $name1=$row[2]; $name2=$row[3];
        $bid=$wpdb->get_var($wpdb->prepare("SELECT building_id FROM {$p}buildings WHERE building_number=%d",$bn));
        $uid=null;
        if($bid) $uid=$wpdb->get_var($wpdb->prepare("SELECT unit_id FROM {$p}units WHERE building_id=%d AND unit_number=%d",$bid,$un));
        if(!$uid){$skipped++;continue;}
        $wpdb->insert("{$p}meeting_attendance",array("meeting_id"=>$mid,"unit_id"=>$uid,"attendee_name"=>$name1,"attendee_name_2"=>$name2,"signed_in"=>1));
        $imported++;
    }
    wp_send_json_success("Imported $imported attendance records, skipped $skipped (meeting ID: $mid)");
});