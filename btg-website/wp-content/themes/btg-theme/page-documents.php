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

<!-- Documents List (dynamic: wp_btg_documents, public docs only) -->
<section class="btg-section btg-section-alt">
    <div class="btg-container">
        <h2 class="btg-section-title">Available Documents</h2>
        <?php
        global $wpdb;
        $btg_docs_table = $wpdb->prefix . 'btg_documents';
        $btg_docs = $wpdb->get_results( "SELECT title, category, description, file_path, file_size, created_at FROM {$btg_docs_table} WHERE is_active = 1 AND requires_auth = 0 ORDER BY category ASC, created_at DESC" );
        if ( $btg_docs ) :
            $btg_cat_labels = array(
                'governing_docs' => 'Governing Documents', 'rules' => 'Rules & Regulations',
                'meeting_minutes' => 'Meeting Minutes', 'minutes' => 'Meeting Minutes',
                'forms' => 'Forms & Applications', 'form' => 'Forms & Applications',
                'financials' => 'Financial Reports', 'financial' => 'Financial Reports',
                'budget' => 'Budget', 'insurance' => 'Insurance & Safety',
                'contracts' => 'Contracts', 'inspection_reports' => 'Inspection Reports',
                'director_disclosures' => 'Director Disclosures', 'notices' => 'Notices',
                'template' => 'Templates', 'other' => 'General',
            );
            $btg_upload = wp_upload_dir();
            $btg_base = trailingslashit( $btg_upload['baseurl'] ) . 'btg-documents/';
            $btg_grouped = array();
            foreach ( $btg_docs as $btg_doc ) {
                $btg_label = ( isset( $btg_doc->category ) && isset( $btg_cat_labels[ $btg_doc->category ] ) ) ? $btg_cat_labels[ $btg_doc->category ] : 'General';
                $btg_grouped[ $btg_label ][] = $btg_doc;
            }
            ksort( $btg_grouped );
            foreach ( $btg_grouped as $btg_label => $btg_items ) : ?>
                <h3 class="btg-doc-group-title"><?php echo esc_html( $btg_label ); ?></h3>
                <?php foreach ( $btg_items as $btg_doc ) :
                    $btg_file = basename( $btg_doc->file_path );
                    $btg_ext  = strtoupper( pathinfo( $btg_file, PATHINFO_EXTENSION ) );
                    $btg_size = ! empty( $btg_doc->file_size ) ? size_format( (int) $btg_doc->file_size ) : '';
                    $btg_date = ! empty( $btg_doc->created_at ) ? mysql2date( 'M j, Y', $btg_doc->created_at ) : '';
                    ?>
                    <div class="btg-doc-item">
                        <div class="doc-file-icon"><?php echo esc_html( $btg_ext ? $btg_ext : 'DOC' ); ?></div>
                        <div class="doc-info">
                            <strong><?php echo esc_html( $btg_doc->title ); ?></strong>
                            <?php if ( ! empty( $btg_doc->description ) ) : ?><p><?php echo esc_html( $btg_doc->description ); ?></p><?php endif; ?>
                            <span class="doc-meta"><?php echo esc_html( trim( $btg_size . ( $btg_size && $btg_date ? ' · ' : '' ) . $btg_date ) ); ?></span>
                        </div>
                        <a class="doc-download" href="<?php echo esc_url( $btg_base . rawurlencode( $btg_file ) ); ?>" target="_blank" rel="noopener">Download</a>
                    </div>
                <?php endforeach;
            endforeach;
        else : ?>
            <p class="no-events-message">Documents will be uploaded soon. Please check back, or contact the office if you need a specific document.</p>
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
