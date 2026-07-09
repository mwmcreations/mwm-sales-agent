<?php
/**
 * Template Name: Photo Gallery
 */
get_header();
$u = content_url( '/uploads/2026/06/' );
$photos = array(
    'drone' => array(
        'label' => 'Aerial Views',
        'items' => array('BTG_DRONE_001.jpg','BTG_DRONE_004.jpg','BTG_DRONE_005.jpg','BTG_DRONE_006.jpg','BTG_DRONE_007.jpg','BTG_DRONE_009.jpg','BTG_DRONE_016.jpg','BTG_DRONE_018.jpg'),
    ),
    'exterior' => array(
        'label' => 'Exteriors',
        'items' => array('BTG_EXTERIOR_001.jpg','BTG_EXTERIOR_005.jpg','BTG_EXTERIOR_008.jpg','BTG_EXTERIOR_011.jpg','BTG_EXTERIOR_018.jpg','BTG_EXTERIOR_029.jpg','BTG_EXTERIOR_031.jpg','BTG_EXTERIOR_032.jpg','BTG_EXTERIOR_033.jpg','BTG_EXTERIOR_036.jpg','BTG_EXTERIOR_038.jpg'),
    ),
    'pool' => array(
        'label' => 'Pool',
        'items' => array('BTG_POOL_001.jpg','BTG_POOL_002.jpg','BTG_POOL_004.jpg','BTG_POOL_007.jpg'),
    ),
    'clubhouse' => array(
        'label' => 'Clubhouse',
        'items' => array('BTG_CLUBHOUSE_002.jpg','BTG_CLUBHOUSE_004.jpg','BTG_CLUBHOUSE_009.jpg','BTG_CLUBHOUSE_010.jpg','BTG_CLUBHOUSE_013.jpg','BTG_CLUBHOUSE_015.jpg','BTG_CLUBHOUSE_017.jpg','BTG_CLUBHOUSE_018.jpg'),
    ),
    'gym' => array(
        'label' => 'Fitness Center',
        'items' => array('BTG_GYM_001.jpg','BTG_GYM_007.jpg','BTG_GYM_009.jpg'),
    ),
    'bbq' => array(
        'label' => 'BBQ Area',
        'items' => array('BTG_BARBECUE_AREA_006.jpg'),
    ),
    'office' => array(
        'label' => 'Leasing Office',
        'items' => array('BTG_LEASING_OFFICE_001.jpg','BTG_LEASING_OFFICE_002.jpg','BTG_LEASING_OFFICE_003.jpg'),
    ),
);
$filter = isset( $_GET['cat'] ) ? sanitize_key( $_GET['cat'] ) : '';
?>

<!-- Hero Banner -->
<section class="btg-section" style="background:var(--btg-green-dark);color:#fff;text-align:center;padding:48px 0;">
    <div class="btg-container">
        <h1 style="color:#fff;font-size:2.2rem;margin-bottom:8px;">Photo Gallery</h1>
        <p style="color:#A5D6A7;font-size:1.1rem;">A look at life at Bent Tree Gardens West</p>
    </div>
</section>

<section class="btg-section">
    <div class="btg-container">

        <!-- Category Filters -->
        <div style="text-align:center;margin-bottom:32px;">
            <a href="<?php echo esc_url( get_permalink() ); ?>"
               class="btg-btn <?php echo empty($filter) ? 'btg-btn-green' : 'btg-btn-outline'; ?>"
               style="margin:4px;font-size:13px;padding:8px 16px;<?php echo empty($filter) ? '' : 'border-color:var(--btg-green);color:var(--btg-green);'; ?>">
                All Photos
            </a>
            <?php foreach ( $photos as $slug => $cat ) : ?>
                <a href="<?php echo esc_url( add_query_arg( 'cat', $slug, get_permalink() ) ); ?>"
                   class="btg-btn <?php echo $filter === $slug ? 'btg-btn-green' : 'btg-btn-outline'; ?>"
                   style="margin:4px;font-size:13px;padding:8px 16px;<?php echo $filter === $slug ? '' : 'border-color:var(--btg-green);color:var(--btg-green);'; ?>">
                    <?php echo esc_html( $cat['label'] ); ?>
                </a>
            <?php endforeach; ?>
        </div>

        <!-- Photo Grid -->
        <div class="btg-gallery-grid">
            <?php
            foreach ( $photos as $slug => $cat ) :
                if ( $filter && $filter !== $slug ) continue;
                foreach ( $cat['items'] as $img ) :
                    $alt = str_replace( array('BTG_','_','.jpg'), array('',  ' ', ''), $img );
            ?>
                <div class="btg-gallery-item" data-category="<?php echo esc_attr( $slug ); ?>">
                    <img src="<?php echo esc_url( $u . $img ); ?>"
                         alt="<?php echo esc_attr( trim( $alt ) ); ?>"
                         loading="lazy">
                    <div class="btg-gallery-overlay">
                        <span><?php echo esc_html( $cat['label'] ); ?></span>
                    </div>
                </div>
            <?php
                endforeach;
            endforeach;
            ?>
        </div>
    </div>
</section>

<?php get_footer(); ?>