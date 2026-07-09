<?php
/**
 * Bent Tree Gardens West — Theme Functions
 *
 * @package BTG_Theme
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

define( 'BTG_THEME_VERSION', '1.3.0' );

/**
 * ──────────────────────────────────────────────
 *  THEME SETUP
 * ──────────────────────────────────────────────
 */
function btg_theme_setup() {
    // Title tag support
    add_theme_support( 'title-tag' );

    // Post thumbnails
    add_theme_support( 'post-thumbnails' );
    add_image_size( 'btg-hero', 1920, 800, true );
    add_image_size( 'btg-card', 600, 400, true );
    add_image_size( 'btg-gallery', 800, 600, true );
    add_image_size( 'btg-thumbnail', 300, 200, true );

    // Custom logo
    add_theme_support( 'custom-logo', array(
        'height'      => 100,
        'width'       => 300,
        'flex-height' => true,
        'flex-width'  => true,
    ) );

    // HTML5
    add_theme_support( 'html5', array(
        'search-form', 'comment-form', 'comment-list', 'gallery', 'caption', 'style', 'script',
    ) );

    // Register navigation menus
    register_nav_menus( array(
        'primary'   => 'Primary Navigation',
        'footer'    => 'Footer Navigation',
        'resident'  => 'Resident Portal Menu',
    ) );

    // Editor styles
    add_theme_support( 'editor-styles' );

    // Custom background
    add_theme_support( 'custom-background', array(
        'default-color' => 'fafafa',
    ) );
}
add_action( 'after_setup_theme', 'btg_theme_setup' );

/**
 * ──────────────────────────────────────────────
 *  ENQUEUE STYLES & SCRIPTS
 * ──────────────────────────────────────────────
 */
function btg_enqueue_assets() {
    // Main stylesheet
    wp_enqueue_style(
        'btg-style',
        get_stylesheet_uri(),
        array(),
        BTG_THEME_VERSION
    );

    // Custom theme JS
    wp_enqueue_script(
        'btg-scripts',
        get_template_directory_uri() . '/assets/js/btg-main.js',
        array(),
        BTG_THEME_VERSION,
        true
    );

    // Localize script with theme data
    wp_localize_script( 'btg-scripts', 'btgData', array(
        'ajaxUrl'  => admin_url( 'admin-ajax.php' ),
        'themeUrl' => get_template_directory_uri(),
        'nonce'    => wp_create_nonce( 'btg_nonce' ),
    ) );
}
add_action( 'wp_enqueue_scripts', 'btg_enqueue_assets' );

/**
 * ──────────────────────────────────────────────
 *  REGISTER SIDEBARS / WIDGET AREAS
 * ──────────────────────────────────────────────
 */
function btg_widgets_init() {
    register_sidebar( array(
        'name'          => 'Footer Column 1',
        'id'            => 'footer-1',
        'before_widget' => '<div class="btg-footer-widget">',
        'after_widget'  => '</div>',
        'before_title'  => '<h4>',
        'after_title'   => '</h4>',
    ) );

    register_sidebar( array(
        'name'          => 'Footer Column 2',
        'id'            => 'footer-2',
        'before_widget' => '<div class="btg-footer-widget">',
        'after_widget'  => '</div>',
        'before_title'  => '<h4>',
        'after_title'   => '</h4>',
    ) );

    register_sidebar( array(
        'name'          => 'Sidebar',
        'id'            => 'sidebar-1',
        'before_widget' => '<div class="btg-sidebar-widget">',
        'after_widget'  => '</div>',
        'before_title'  => '<h3>',
        'after_title'   => '</h3>',
    ) );
}
add_action( 'widgets_init', 'btg_widgets_init' );

/**
 * ──────────────────────────────────────────────
 *  CUSTOM POST TYPES
 * ──────────────────────────────────────────────
 */
function btg_register_post_types() {
    // News & Announcements
    register_post_type( 'btg_news', array(
        'labels' => array(
            'name'          => 'News & Announcements',
            'singular_name' => 'Announcement',
            'add_new_item'  => 'Add New Announcement',
            'edit_item'     => 'Edit Announcement',
            'menu_name'     => 'News',
        ),
        'public'        => true,
        'has_archive'   => true,
        'menu_icon'     => 'dashicons-megaphone',
        'menu_position' => 25,
        'supports'      => array( 'title', 'editor', 'thumbnail', 'excerpt', 'revisions' ),
        'rewrite'       => array( 'slug' => 'news' ),
        'show_in_rest'  => true,
    ) );

    // Amenities
    register_post_type( 'btg_amenity', array(
        'labels' => array(
            'name'          => 'Amenities',
            'singular_name' => 'Amenity',
            'add_new_item'  => 'Add New Amenity',
            'edit_item'     => 'Edit Amenity',
            'menu_name'     => 'Amenities',
        ),
        'public'        => true,
        'has_archive'   => true,
        'menu_icon'     => 'dashicons-palmtree',
        'menu_position' => 26,
        'supports'      => array( 'title', 'editor', 'thumbnail', 'excerpt', 'page-attributes' ),
        'rewrite'       => array( 'slug' => 'amenities' ),
        'show_in_rest'  => true,
    ) );

    // Community Events (Calendar)
    register_post_type( 'btg_event', array(
        'labels' => array(
            'name'          => 'Community Events',
            'singular_name' => 'Event',
            'add_new_item'  => 'Add New Event',
            'edit_item'     => 'Edit Event',
            'menu_name'     => 'Events',
        ),
        'public'        => true,
        'has_archive'   => true,
        'menu_icon'     => 'dashicons-calendar-alt',
        'menu_position' => 27,
        'supports'      => array( 'title', 'editor', 'thumbnail' ),
        'rewrite'       => array( 'slug' => 'events' ),
        'show_in_rest'  => true,
    ) );

    // FAQ
    register_post_type( 'btg_faq', array(
        'labels' => array(
            'name'          => 'FAQs',
            'singular_name' => 'FAQ',
            'add_new_item'  => 'Add New FAQ',
            'edit_item'     => 'Edit FAQ',
            'menu_name'     => 'FAQs',
        ),
        'public'        => true,
        'has_archive'   => true,
        'menu_icon'     => 'dashicons-editor-help',
        'menu_position' => 28,
        'supports'      => array( 'title', 'editor', 'page-attributes' ),
        'rewrite'       => array( 'slug' => 'faq' ),
        'show_in_rest'  => true,
    ) );
}
add_action( 'init', 'btg_register_post_types' );

/**
 * ──────────────────────────────────────────────
 *  CUSTOM TAXONOMIES
 * ──────────────────────────────────────────────
 */
function btg_register_taxonomies() {
    // News Categories
    register_taxonomy( 'news_category', 'btg_news', array(
        'labels' => array(
            'name'          => 'News Categories',
            'singular_name' => 'News Category',
        ),
        'hierarchical' => true,
        'rewrite'      => array( 'slug' => 'news-category' ),
        'show_in_rest' => true,
    ) );

    // Gallery Categories
    register_taxonomy( 'gallery_category', 'attachment', array(
        'labels' => array(
            'name'          => 'Gallery Categories',
            'singular_name' => 'Gallery Category',
        ),
        'hierarchical' => true,
        'rewrite'      => array( 'slug' => 'gallery-category' ),
        'show_in_rest' => true,
    ) );
}
add_action( 'init', 'btg_register_taxonomies' );

/**
 * ──────────────────────────────────────────────
 *  EVENT META BOXES
 * ──────────────────────────────────────────────
 */
function btg_add_event_meta_boxes() {
    add_meta_box(
        'btg_event_details',
        'Event Details',
        'btg_event_details_callback',
        'btg_event',
        'side',
        'high'
    );
}
add_action( 'add_meta_boxes', 'btg_add_event_meta_boxes' );

function btg_event_details_callback( $post ) {
    wp_nonce_field( 'btg_event_meta', 'btg_event_nonce' );

    $date     = get_post_meta( $post->ID, '_btg_event_date', true );
    $time     = get_post_meta( $post->ID, '_btg_event_time', true );
    $location = get_post_meta( $post->ID, '_btg_event_location', true );

    ?>
    <p>
        <label><strong>Date:</strong></label><br>
        <input type="date" name="btg_event_date" value="<?php echo esc_attr( $date ); ?>" style="width:100%;">
    </p>
    <p>
        <label><strong>Time:</strong></label><br>
        <input type="time" name="btg_event_time" value="<?php echo esc_attr( $time ); ?>" style="width:100%;">
    </p>
    <p>
        <label><strong>Location:</strong></label><br>
        <input type="text" name="btg_event_location" value="<?php echo esc_attr( $location ); ?>" style="width:100%;" placeholder="e.g., Clubhouse, Pool Area">
    </p>
    <?php
}

function btg_save_event_meta( $post_id ) {
    if ( ! isset( $_POST['btg_event_nonce'] ) || ! wp_verify_nonce( $_POST['btg_event_nonce'], 'btg_event_meta' ) ) {
        return;
    }
    if ( defined( 'DOING_AUTOSAVE' ) && DOING_AUTOSAVE ) {
        return;
    }

    if ( isset( $_POST['btg_event_date'] ) ) {
        update_post_meta( $post_id, '_btg_event_date', sanitize_text_field( $_POST['btg_event_date'] ) );
    }
    if ( isset( $_POST['btg_event_time'] ) ) {
        update_post_meta( $post_id, '_btg_event_time', sanitize_text_field( $_POST['btg_event_time'] ) );
    }
    if ( isset( $_POST['btg_event_location'] ) ) {
        update_post_meta( $post_id, '_btg_event_location', sanitize_text_field( $_POST['btg_event_location'] ) );
    }
}
add_action( 'save_post_btg_event', 'btg_save_event_meta' );

/**
 * ──────────────────────────────────────────────
 *  SHORTCODES
 * ──────────────────────────────────────────────
 */

// [btg_board_members] — Display board members grid
function btg_board_members_shortcode( $atts ) {
    global $wpdb;
    $prefix  = $wpdb->prefix . 'btg_';
    $members = $wpdb->get_results( "SELECT * FROM {$prefix}board_members WHERE is_active = 1 ORDER BY display_order, full_name" );

    if ( empty( $members ) ) {
        return '<p>Board member information coming soon.</p>';
    }

    ob_start();
    echo '<div class="btg-grid btg-grid-3">';
    foreach ( $members as $m ) {
        $initials = implode( '', array_map( function( $w ) { return strtoupper( $w[0] ?? '' ); }, explode( ' ', $m->full_name ) ) );
        ?>
        <div class="btg-board-member">
            <div class="member-icon"><?php echo esc_html( $initials ); ?></div>
            <h3><?php echo esc_html( $m->full_name ); ?></h3>
            <div class="member-title"><?php echo esc_html( $m->title ); ?></div>
            <?php if ( $m->building_number ) : ?>
                <div class="member-building">Building <?php echo esc_html( $m->building_number ); ?></div>
            <?php endif; ?>
            <?php if ( $m->bio ) : ?>
                <p class="member-bio"><?php echo esc_html( $m->bio ); ?></p>
            <?php endif; ?>
            <?php if ( $m->committees ) : ?>
                <p class="member-bio" style="margin-top:8px;font-style:italic;">
                    Committees: <?php echo esc_html( $m->committees ); ?>
                </p>
            <?php endif; ?>
            <?php if ( $m->contact_email ) : ?>
                <p style="margin-top:12px;">
                    <a href="mailto:<?php echo esc_attr( $m->contact_email ); ?>" class="btg-btn btg-btn-green" style="font-size:12px;padding:8px 16px;">
                        Contact
                    </a>
                </p>
            <?php endif; ?>
        </div>
        <?php
    }
    echo '</div>';
    return ob_get_clean();
}
add_shortcode( 'btg_board_members', 'btg_board_members_shortcode' );

// [btg_upcoming_events limit="5"] — Display upcoming events
function btg_upcoming_events_shortcode( $atts ) {
    $atts = shortcode_atts( array( 'limit' => 5 ), $atts );

    $events = get_posts( array(
        'post_type'      => 'btg_event',
        'posts_per_page' => intval( $atts['limit'] ),
        'meta_key'       => '_btg_event_date',
        'orderby'        => 'meta_value',
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

    if ( empty( $events ) ) {
        return '<p>No upcoming events scheduled.</p>';
    }

    ob_start();
    foreach ( $events as $event ) {
        $date     = get_post_meta( $event->ID, '_btg_event_date', true );
        $time     = get_post_meta( $event->ID, '_btg_event_time', true );
        $location = get_post_meta( $event->ID, '_btg_event_location', true );
        $ts       = strtotime( $date );
        ?>
        <div class="btg-event">
            <div class="btg-event-date">
                <div class="month"><?php echo date( 'M', $ts ); ?></div>
                <div class="day"><?php echo date( 'j', $ts ); ?></div>
            </div>
            <div class="btg-event-info">
                <h4><?php echo esc_html( $event->post_title ); ?></h4>
                <p>
                    <?php if ( $time ) echo esc_html( date( 'g:i A', strtotime( $time ) ) ); ?>
                    <?php if ( $time && $location ) echo ' &bull; '; ?>
                    <?php if ( $location ) echo esc_html( $location ); ?>
                </p>
                <?php if ( $event->post_content ) : ?>
                    <p style="margin-top:4px;"><?php echo esc_html( wp_trim_words( $event->post_content, 20 ) ); ?></p>
                <?php endif; ?>
            </div>
        </div>
        <?php
    }
    return ob_get_clean();
}
add_shortcode( 'btg_upcoming_events', 'btg_upcoming_events_shortcode' );

// [btg_latest_news limit="3"] — Display latest news
function btg_latest_news_shortcode( $atts ) {
    $atts = shortcode_atts( array( 'limit' => 3 ), $atts );

    $news = get_posts( array(
        'post_type'      => 'btg_news',
        'posts_per_page' => intval( $atts['limit'] ),
        'orderby'        => 'date',
        'order'          => 'DESC',
    ) );

    if ( empty( $news ) ) {
        return '<p>No announcements at this time.</p>';
    }

    ob_start();
    echo '<div class="btg-grid btg-grid-3">';
    foreach ( $news as $post ) {
        ?>
        <div class="btg-card">
            <?php if ( has_post_thumbnail( $post->ID ) ) : ?>
                <div class="btg-card-img" style="background-image:url(<?php echo esc_url( get_the_post_thumbnail_url( $post->ID, 'btg-card' ) ); ?>);"></div>
            <?php endif; ?>
            <div class="btg-card-body">
                <h3><?php echo esc_html( $post->post_title ); ?></h3>
                <p style="font-size:12px;color:var(--btg-text-light);margin-bottom:8px;">
                    <?php echo date( 'F j, Y', strtotime( $post->post_date ) ); ?>
                </p>
                <p><?php echo esc_html( wp_trim_words( $post->post_content, 25 ) ); ?></p>
                <a href="<?php echo get_permalink( $post->ID ); ?>" class="btg-btn btg-btn-green" style="font-size:12px;padding:8px 16px;">
                    Read More
                </a>
            </div>
        </div>
        <?php
    }
    echo '</div>';
    return ob_get_clean();
}
add_shortcode( 'btg_latest_news', 'btg_latest_news_shortcode' );

/**
 * ──────────────────────────────────────────────
 *  THEME CUSTOMIZER
 * ──────────────────────────────────────────────
 */
function btg_customize_register( $wp_customize ) {
    // Hero Section
    $wp_customize->add_section( 'btg_hero', array(
        'title'    => 'Homepage Hero',
        'priority' => 30,
    ) );

    $wp_customize->add_setting( 'btg_hero_title', array(
        'default'           => 'Welcome to Bent Tree Gardens West',
        'sanitize_callback' => 'sanitize_text_field',
    ) );
    $wp_customize->add_control( 'btg_hero_title', array(
        'label'   => 'Hero Title',
        'section' => 'btg_hero',
        'type'    => 'text',
    ) );

    $wp_customize->add_setting( 'btg_hero_subtitle', array(
        'default'           => 'A welcoming gated community in Boynton Beach, Florida',
        'sanitize_callback' => 'sanitize_text_field',
    ) );
    $wp_customize->add_control( 'btg_hero_subtitle', array(
        'label'   => 'Hero Subtitle',
        'section' => 'btg_hero',
        'type'    => 'textarea',
    ) );

    $wp_customize->add_setting( 'btg_hero_image', array(
        'sanitize_callback' => 'esc_url_raw',
    ) );
    $wp_customize->add_control( new WP_Customize_Image_Control( $wp_customize, 'btg_hero_image', array(
        'label'   => 'Hero Background Image',
        'section' => 'btg_hero',
    ) ) );

    // Contact Information
    $wp_customize->add_section( 'btg_contact', array(
        'title'    => 'Contact Information',
        'priority' => 35,
    ) );

    $contact_fields = array(
        'btg_phone'          => array( 'Phone Number', '561-374-3360' ),
        'btg_email'          => array( 'Email', '' ),
        'btg_address'        => array( 'Address', '9990 Pineapple Tree Dr, Boynton Beach, FL 33436' ),
        'btg_office_hours'   => array( 'Office Hours', 'Mon-Fri: 9:00 AM - 5:00 PM' ),
        'btg_emergency_phone'=> array( 'Emergency Phone', '' ),
    );

    foreach ( $contact_fields as $id => $field ) {
        $wp_customize->add_setting( $id, array(
            'default'           => $field[1],
            'sanitize_callback' => 'sanitize_text_field',
        ) );
        $wp_customize->add_control( $id, array(
            'label'   => $field[0],
            'section' => 'btg_contact',
            'type'    => 'text',
        ) );
    }
}
add_action( 'customize_register', 'btg_customize_register' );

/**
 * ──────────────────────────────────────────────
 *  SECURITY HEADERS
 * ──────────────────────────────────────────────
 */
function btg_security_headers() {
    if ( ! is_admin() ) {
        header( 'X-Content-Type-Options: nosniff' );
        header( 'X-Frame-Options: SAMEORIGIN' );
        header( 'X-XSS-Protection: 1; mode=block' );
        header( 'Referrer-Policy: strict-origin-when-cross-origin' );
    }
}
add_action( 'send_headers', 'btg_security_headers' );

/**
 * ──────────────────────────────────────────────
 *  HELPER FUNCTIONS
 * ──────────────────────────────────────────────
 */
function btg_get_contact( $key ) {
    return get_theme_mod( $key, '' );
}


/**
 * Route CPT archives to custom theme templates
 */
add_filter( 'template_include', function( $template ) {
    if ( is_post_type_archive( 'btg_amenity' ) ) {
        $custom = get_template_directory() . '/page-amenities.php';
        if ( file_exists( $custom ) ) return $custom;
    }
    return $template;
} );

/**
 * ——————————————————————————————
 *  CUSTOM LOGIN PAGE BRANDING
 * ——————————————————————————————
 */

// Replace WordPress logo with BTG logo
add_action( 'login_enqueue_scripts', function() {
    $logo_url = get_template_directory_uri() . '/assets/images/logo.png';
    echo '<style type="text/css">
        #login h1 a, .login h1 a {
            background-image: url(' . esc_url( $logo_url ) . ');
            background-size: contain;
            background-repeat: no-repeat;
            background-position: center;
            width: 300px;
            height: 120px;
            margin-bottom: 10px;
        }
        body.login {
            background-color: #f5f1eb;
        }
        .login #backtoblog a, .login #nav a {
            color: #2E7D32;
        }
        .login #backtoblog a:hover, .login #nav a:hover {
            color: #C8A951;
        }
        .wp-core-ui .button-primary {
            background: #2E7D32;
            border-color: #256829;
        }
        .wp-core-ui .button-primary:hover {
            background: #256829;
            border-color: #1e5522;
        }
        .login form {
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        }
    </style>';
} );

// Point login logo link to site homepage
add_filter( 'login_headerurl', function() {
    return home_url();
} );

// Change login logo title text
add_filter( 'login_headertext', function() {
    return 'Bent Tree Gardens West';
} );

// Replace login page credit text
add_action( 'login_footer', function() {
    echo '<script>document.getElementById("backtoblog").nextElementSibling.innerHTML = \'<a href="https://mwmcreations.com" target="_blank" style="color:#2E7D32;">Built by MWM Creations &amp; Studios</a>\';</script>';
} );

// Replace admin footer credit text
add_filter( 'admin_footer_text', function() {
    return '<a href="https://mwmcreations.com" target="_blank" style="color:#2E7D32;">Built by MWM Creations &amp; Studios</a>';
} );

/**
 * ââââââââââââââââââââââââââââââââââââââââââââââ
 *  APPLICATION FORMS â Rental & Transfer
 * ââââââââââââââââââââââââââââââââââââââââââââââ
 */

// [btg_rental_application] â Rental application form
function btg_rental_application_shortcode() {
    $success = '';
    if ( isset( $_POST['btg_rental_nonce'] ) && wp_verify_nonce( $_POST['btg_rental_nonce'], 'btg_rental_app' ) ) {
        $data = array(
            'applicant_name'   => sanitize_text_field( $_POST['applicant_name'] ?? '' ),
            'applicant_email'  => sanitize_email( $_POST['applicant_email'] ?? '' ),
            'applicant_phone'  => sanitize_text_field( $_POST['applicant_phone'] ?? '' ),
            'unit_requested'   => sanitize_text_field( $_POST['unit_requested'] ?? '' ),
            'building_number'  => sanitize_text_field( $_POST['building_number'] ?? '' ),
            'owner_name'       => sanitize_text_field( $_POST['owner_name'] ?? '' ),
            'move_in_date'     => sanitize_text_field( $_POST['move_in_date'] ?? '' ),
            'lease_term'       => sanitize_text_field( $_POST['lease_term'] ?? '' ),
            'num_occupants'    => intval( $_POST['num_occupants'] ?? 1 ),
            'has_pets'         => sanitize_text_field( $_POST['has_pets'] ?? 'No' ),
            'pet_details'      => sanitize_textarea_field( $_POST['pet_details'] ?? '' ),
            'vehicles'         => sanitize_textarea_field( $_POST['vehicles'] ?? '' ),
            'additional_notes' => sanitize_textarea_field( $_POST['additional_notes'] ?? '' ),
        );

        // Save to database
        global $wpdb;
        $wpdb->insert(
            $wpdb->prefix . 'btg_rental_applications',
            array_merge( $data, array( 'status' => 'pending', 'submitted_at' => current_time( 'mysql' ) ) )
        );

        // Send email to admin
        $admin_email = 'admin@benttreegardenswest.com';
        $subject = 'New Rental Application - ' . $data['applicant_name'] . ' (Bldg ' . $data['building_number'] . ' Unit ' . $data['unit_requested'] . ')';
        $body  = "A new rental application has been submitted:\n\n";
        $body .= "Applicant: {$data['applicant_name']}\n";
        $body .= "Email: {$data['applicant_email']}\n";
        $body .= "Phone: {$data['applicant_phone']}\n";
        $body .= "Building: {$data['building_number']}, Unit: {$data['unit_requested']}\n";
        $body .= "Unit Owner: {$data['owner_name']}\n";
        $body .= "Desired Move-In: {$data['move_in_date']}\n";
        $body .= "Lease Term: {$data['lease_term']}\n";
        $body .= "Number of Occupants: {$data['num_occupants']}\n";
        $body .= "Pets: {$data['has_pets']}" . ( $data['pet_details'] ? " - {$data['pet_details']}" : '' ) . "\n";
        $body .= "Vehicles: {$data['vehicles']}\n";
        if ( $data['additional_notes'] ) $body .= "Notes: {$data['additional_notes']}\n";
        $body .= "\nâ Submitted via Bent Tree Gardens West website";

        wp_mail( $admin_email, $subject, $body, array( 'Reply-To: ' . $data['applicant_email'] ) );
        $success = 'rental';
    }

    ob_start();
    if ( $success === 'rental' ) : ?>
        <div class="btg-notice btg-notice-success" style="max-width:600px;margin:0 auto;padding:24px;text-align:center;">
            <h3 style="color:var(--btg-green,#2E7D32);margin-bottom:8px;">Application Submitted Successfully</h3>
            <p>Thank you for your rental application. The Board will review it and contact you within 5-10 business days. A copy has been sent to the management office.</p>
        </div>
    <?php else : ?>
        <form method="post" style="max-width:640px;margin:0 auto;background:#fff;border-radius:12px;padding:32px;box-shadow:0 2px 8px rgba(0,0,0,.08);">
            <?php wp_nonce_field( 'btg_rental_app', 'btg_rental_nonce' ); ?>
            <h3 style="margin-top:0;color:var(--btg-green,#2E7D32);">Rental Application</h3>
            <p style="color:#666;margin-bottom:24px;">Please fill out all required fields. Applications are reviewed by the Board within 5-10 business days.</p>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div style="grid-column:span 2"><label style="font-weight:600;display:block;margin-bottom:4px;">Full Name *</label>
                <input type="text" name="applicant_name" required style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;" placeholder="Your full legal name"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Email *</label>
                <input type="email" name="applicant_email" required style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Phone *</label>
                <input type="tel" name="applicant_phone" required style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Building # *</label>
                <select name="building_number" required style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;">
                    <option value="">Select...</option>
                    <?php for ( $i = 1; $i <= 13; $i++ ) echo "<option value=\"$i\">Building $i</option>"; ?>
                </select></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Unit # *</label>
                <input type="text" name="unit_requested" required style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;" placeholder="e.g. 101"></div>

                <div style="grid-column:span 2"><label style="font-weight:600;display:block;margin-bottom:4px;">Unit Owner Name *</label>
                <input type="text" name="owner_name" required style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;" placeholder="Name of the unit owner authorizing this rental"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Desired Move-In Date *</label>
                <input type="date" name="move_in_date" required style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Lease Term</label>
                <select name="lease_term" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;">
                    <option value="12 months">12 Months</option>
                    <option value="6 months">6 Months</option>
                    <option value="Month-to-month">Month to Month</option>
                    <option value="Other">Other</option>
                </select></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Number of Occupants *</label>
                <input type="number" name="num_occupants" value="1" min="1" max="10" required style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Pets?</label>
                <select name="has_pets" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;">
                    <option value="No">No</option>
                    <option value="Yes">Yes</option>
                </select></div>

                <div style="grid-column:span 2"><label style="font-weight:600;display:block;margin-bottom:4px;">Pet Details (if applicable)</label>
                <input type="text" name="pet_details" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;" placeholder="Type, breed, weight"></div>

                <div style="grid-column:span 2"><label style="font-weight:600;display:block;margin-bottom:4px;">Vehicles (make, model, color, plate)</label>
                <textarea name="vehicles" rows="2" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;" placeholder="List each vehicle on a separate line"></textarea></div>

                <div style="grid-column:span 2"><label style="font-weight:600;display:block;margin-bottom:4px;">Additional Notes</label>
                <textarea name="additional_notes" rows="3" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></textarea></div>
            </div>

            <div style="margin-top:24px;">
                <button type="submit" style="background:var(--btg-green,#2E7D32);color:#fff;border:none;padding:14px 32px;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;width:100%;">
                    Submit Rental Application
                </button>
                <p style="font-size:12px;color:#999;margin-top:12px;text-align:center;">By submitting, you agree that the information provided is accurate and complete. A background check may be required as part of the approval process.</p>
            </div>
        </form>
    <?php endif;
    return ob_get_clean();
}
add_shortcode( 'btg_rental_application', 'btg_rental_application_shortcode' );

// [btg_transfer_application] â Ownership transfer application
function btg_transfer_application_shortcode() {
    $success = '';
    if ( isset( $_POST['btg_transfer_nonce'] ) && wp_verify_nonce( $_POST['btg_transfer_nonce'], 'btg_transfer_app' ) ) {
        $data = array(
            'current_owner'    => sanitize_text_field( $_POST['current_owner'] ?? '' ),
            'buyer_name'       => sanitize_text_field( $_POST['buyer_name'] ?? '' ),
            'buyer_email'      => sanitize_email( $_POST['buyer_email'] ?? '' ),
            'buyer_phone'      => sanitize_text_field( $_POST['buyer_phone'] ?? '' ),
            'building_number'  => sanitize_text_field( $_POST['building_number'] ?? '' ),
            'unit_number'      => sanitize_text_field( $_POST['unit_number'] ?? '' ),
            'closing_date'     => sanitize_text_field( $_POST['closing_date'] ?? '' ),
            'title_company'    => sanitize_text_field( $_POST['title_company'] ?? '' ),
            'realtor_name'     => sanitize_text_field( $_POST['realtor_name'] ?? '' ),
            'realtor_phone'    => sanitize_text_field( $_POST['realtor_phone'] ?? '' ),
            'additional_notes' => sanitize_textarea_field( $_POST['additional_notes'] ?? '' ),
        );

        // Save to database
        global $wpdb;
        $wpdb->insert(
            $wpdb->prefix . 'btg_transfer_applications',
            array_merge( $data, array( 'status' => 'pending', 'submitted_at' => current_time( 'mysql' ) ) )
        );

        $admin_email = 'admin@benttreegardenswest.com';
        $subject = 'Ownership Transfer Application - Bldg ' . $data['building_number'] . ' Unit ' . $data['unit_number'];
        $body  = "An ownership transfer application has been submitted:\n\n";
        $body .= "Current Owner: {$data['current_owner']}\n";
        $body .= "New Buyer: {$data['buyer_name']}\n";
        $body .= "Buyer Email: {$data['buyer_email']}\n";
        $body .= "Buyer Phone: {$data['buyer_phone']}\n";
        $body .= "Building: {$data['building_number']}, Unit: {$data['unit_number']}\n";
        $body .= "Expected Closing Date: {$data['closing_date']}\n";
        $body .= "Title Company: {$data['title_company']}\n";
        $body .= "Realtor: {$data['realtor_name']}" . ( $data['realtor_phone'] ? " ({$data['realtor_phone']})" : '' ) . "\n";
        if ( $data['additional_notes'] ) $body .= "Notes: {$data['additional_notes']}\n";
        $body .= "\nâ Submitted via Bent Tree Gardens West website";

        wp_mail( $admin_email, $subject, $body, array( 'Reply-To: ' . $data['buyer_email'] ) );
        $success = 'transfer';
    }

    ob_start();
    if ( $success === 'transfer' ) : ?>
        <div class="btg-notice btg-notice-success" style="max-width:600px;margin:0 auto;padding:24px;text-align:center;">
            <h3 style="color:var(--btg-green,#2E7D32);margin-bottom:8px;">Transfer Application Submitted</h3>
            <p>Thank you for submitting the ownership transfer application. The management office will process the estoppel letter and contact the title company. Please allow 5-10 business days.</p>
        </div>
    <?php else : ?>
        <form method="post" style="max-width:640px;margin:0 auto;background:#fff;border-radius:12px;padding:32px;box-shadow:0 2px 8px rgba(0,0,0,.08);">
            <?php wp_nonce_field( 'btg_transfer_app', 'btg_transfer_nonce' ); ?>
            <h3 style="margin-top:0;color:var(--btg-green,#2E7D32);">Ownership Transfer Application</h3>
            <p style="color:#666;margin-bottom:24px;">Submit this form when a unit is being sold. An estoppel letter will be prepared for the closing.</p>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div style="grid-column:span 2"><label style="font-weight:600;display:block;margin-bottom:4px;">Current Owner Name *</label>
                <input type="text" name="current_owner" required style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Building # *</label>
                <select name="building_number" required style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;">
                    <option value="">Select...</option>
                    <?php for ( $i = 1; $i <= 13; $i++ ) echo "<option value=\"$i\">Building $i</option>"; ?>
                </select></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Unit # *</label>
                <input type="text" name="unit_number" required style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;" placeholder="e.g. 101"></div>

                <div style="grid-column:span 2;border-top:1px solid #eee;padding-top:16px;margin-top:4px;">
                    <h4 style="margin:0 0 12px;color:var(--btg-green,#2E7D32);">New Buyer Information</h4>
                </div>

                <div style="grid-column:span 2"><label style="font-weight:600;display:block;margin-bottom:4px;">Buyer Full Name *</label>
                <input type="text" name="buyer_name" required style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Buyer Email *</label>
                <input type="email" name="buyer_email" required style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Buyer Phone</label>
                <input type="tel" name="buyer_phone" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Expected Closing Date</label>
                <input type="date" name="closing_date" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Title Company</label>
                <input type="text" name="title_company" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Realtor Name</label>
                <input type="text" name="realtor_name" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></div>

                <div><label style="font-weight:600;display:block;margin-bottom:4px;">Realtor Phone</label>
                <input type="tel" name="realtor_phone" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></div>

                <div style="grid-column:span 2"><label style="font-weight:600;display:block;margin-bottom:4px;">Additional Notes</label>
                <textarea name="additional_notes" rows="3" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;"></textarea></div>
            </div>

            <div style="margin-top:24px;">
                <button type="submit" style="background:var(--btg-green,#2E7D32);color:#fff;border:none;padding:14px 32px;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;width:100%;">
                    Submit Transfer Application
                </button>
                <p style="font-size:12px;color:#999;margin-top:12px;text-align:center;">An estoppel letter fee may apply per FL Statute 718.116. The management office will advise on any outstanding balances.</p>
            </div>
        </form>
    <?php endif;
    return ob_get_clean();
}
add_shortcode( 'btg_transfer_application', 'btg_transfer_application_shortcode' );
