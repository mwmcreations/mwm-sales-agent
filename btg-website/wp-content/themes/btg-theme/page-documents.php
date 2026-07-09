<?php get_header(); ?>

<!-- Hero Banner -->
<section class="page-hero" style="background-image: url('<?php echo esc_url( get_site_url() ); ?>/wp-content/uploads/2026/06/BTG_EXTERIOR_036.jpg');">
    <div class="page-hero-content">
        <h1>Community Documents</h1>
        <p>Access important documents, forms, and community resources</p>
        <div class="page-hero-breadcrumb">
            <a href="<?php echo home_url(); ?>">Home</a> &mdash; Documents
        </div>
    </div>
</section>

<!-- Document Categories Overview -->
<section class="btg-section">
    <div class="btg-container">
        <div class="docs-intro">
            <h2>Document Library</h2>
            <p>Find all the documents you need &mdash; from community rules and regulations to meeting minutes and important forms.</p>
        </div>

        <div class="docs-categories-grid">
            <div class="doc-category-card">
                <div class="doc-cat-icon">&#x1F4DC;</div>
                <h3>Rules &amp; Regulations</h3>
                <p>Community guidelines, bylaws, and declarations that govern our community</p>
            </div>
            <div class="doc-category-card">
                <div class="doc-cat-icon">&#x1F4CB;</div>
                <h3>Meeting Minutes</h3>
                <p>Board meeting minutes and annual meeting records</p>
            </div>
            <div class="doc-category-card">
                <div class="doc-cat-icon">&#x1F4C4;</div>
                <h3>Forms &amp; Applications</h3>
                <p>Parking permits, modification requests, and other essential forms</p>
            </div>
            <div class="doc-category-card">
                <div class="doc-cat-icon">&#x1F4B0;</div>
                <h3>Financial Reports</h3>
                <p>Annual budgets, financial statements, and assessment information</p>
            </div>
            <div class="doc-category-card">
                <div class="doc-cat-icon">&#x1F4E2;</div>
                <h3>Newsletters</h3>
                <p>Community newsletters and announcements archive</p>
            </div>
            <div class="doc-category-card">
                <div class="doc-cat-icon">&#x1F6E1;</div>
                <h3>Insurance &amp; Safety</h3>
                <p>Insurance certificates, emergency procedures, and safety information</p>
            </div>
        </div>
    </div>
</section>

<!-- Documents List -->
<section class="btg-section btg-section-alt">
    <div class="btg-container">
        <h2 class="btg-section-title">Available Documents</h2>

        <?php
        // Query for document attachments or a custom document CPT
        $docs = new WP_Query( array(
            'post_type'      => 'attachment',
            'post_status'    => 'inherit',
            'posts_per_page' => 20,
            'post_mime_type' => array( 'application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ),
            'orderby'        => 'date',
            'order'          => 'DESC',
        ) );

        if ( $docs->have_posts() ) :
            while ( $docs->have_posts() ) : $docs->the_post();
                $file_url  = wp_get_attachment_url( get_the_ID() );
                $file_type = pathinfo( $file_url, PATHINFO_EXTENSION );
                $file_size = size_format( filesize( get_attached_file( get_the_ID() ) ), 1 );
                $icon = ( $file_type === 'pdf' ) ? '&#x1F4D5;' : '&#x1F4C4;';
        ?>
            <div class="btg-doc-item">
                <div class="doc-file-icon"><?php echo $icon; ?></div>
                <div class="doc-info">
                    <h4><?php the_title(); ?></h4>
                    <span><?php echo strtoupper( $file_type ) . ' &bull; ' . $file_size; ?></span>
                </div>
                <a href="<?php echo esc_url( $file_url ); ?>" class="doc-download" target="_blank" rel="noopener">Download</a>
            </div>
        <?php
            endwhile;
            wp_reset_postdata();
        else :
        ?>
            <div class="no-events-message" style="margin-top: 24px;">
                <p>Community documents will be uploaded here soon. Please check back or contact the management office for specific document requests.</p>
            </div>
        <?php endif; ?>
    </div>
</section>

<!-- Contact CTA -->
<section class="btg-section">
    <div class="btg-container">
        <div class="board-cta-box">
            <h3>Need a Specific Document?</h3>
            <p>If you can&rsquo;t find what you&rsquo;re looking for, our management office is happy to help. Contact us and we&rsquo;ll get you the information you need.</p>
            <a href="<?php echo home_url( '/contact/' ); ?>" class="btg-btn btg-btn-green">Request a Document</a>
        </div>
    </div>
</section>

<?php get_footer(); ?>
