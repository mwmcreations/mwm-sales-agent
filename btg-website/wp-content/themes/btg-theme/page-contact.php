<?php get_header(); ?>

<!-- Hero Banner -->
<section class="page-hero" style="background-image: url('<?php echo esc_url( get_site_url() ); ?>/wp-content/uploads/2026/06/BTG_LEASING_OFFICE_001.jpg');">
    <div class="page-hero-content">
        <h1>Contact Us</h1>
        <p>We&rsquo;re here to help. Reach out to our management team anytime.</p>
        <div class="page-hero-breadcrumb">
            <a href="<?php echo home_url(); ?>">Home</a> &mdash; Contact
        </div>
    </div>
</section>

<!-- Contact Info Cards -->
<section class="btg-section">
    <div class="btg-container">
        <div class="contact-info-cards">
            <div class="contact-info-card">
                <div class="card-icon">&#x1F4CD;</div>
                <h3>Our Location</h3>
                <p>9990 Pineapple Tree Dr<br>Boynton Beach, FL 33436</p>
            </div>
            <div class="contact-info-card">
                <div class="card-icon">&#x1F552;</div>
                <h3>Office Hours</h3>
                <p>Monday &ndash; Friday<br>9:00 AM &ndash; 5:00 PM</p>
            </div>
            <div class="contact-info-card">
                <div class="card-icon">&#x2709;</div>
                <h3>Get in Touch</h3>
                <p>info@benttreegardenswest.com<br>We respond within 24 hours</p>
            </div>
        </div>
    </div>
</section>

<!-- Contact Form & Office Photos -->
<section class="btg-section btg-section-alt">
    <div class="btg-container">
        <div class="contact-main-grid">
            <!-- Contact Form -->
            <div class="contact-form-wrapper">
                <h2>Send Us a Message</h2>
                <form class="contact-form" method="post" action="#">
                    <div class="form-row">
                        <div class="form-group">
                            <label for="contact-name">Full Name</label>
                            <input type="text" id="contact-name" name="name" placeholder="Your full name" required>
                        </div>
                        <div class="form-group">
                            <label for="contact-email">Email Address</label>
                            <input type="email" id="contact-email" name="email" placeholder="your@email.com" required>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="contact-subject">Subject</label>
                        <select id="contact-subject" name="subject">
                            <option value="">Select a topic...</option>
                            <option value="general">General Inquiry</option>
                            <option value="maintenance">Maintenance Request</option>
                            <option value="board">Board Communication</option>
                            <option value="parking">Parking &amp; Permits</option>
                            <option value="documents">Document Request</option>
                            <option value="other">Other</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="contact-unit">Unit Number (if resident)</label>
                        <input type="text" id="contact-unit" name="unit" placeholder="e.g. Building 3, Unit 204">
                    </div>
                    <div class="form-group">
                        <label for="contact-message">Message</label>
                        <textarea id="contact-message" name="message" placeholder="How can we help you?" required></textarea>
                    </div>
                    <button type="submit" class="btg-btn btg-btn-green">Send Message</button>
                </form>
            </div>

            <!-- Office Photos -->
            <div class="contact-office-photos">
                <img src="<?php echo esc_url( get_site_url() ); ?>/wp-content/uploads/2026/06/BTG_LEASING_OFFICE_002.jpg" alt="Leasing office interior" loading="lazy">
                <img src="<?php echo esc_url( get_site_url() ); ?>/wp-content/uploads/2026/06/BTG_LEASING_OFFICE_003.jpg" alt="Leasing office workspace" loading="lazy">
                <img src="<?php echo esc_url( get_site_url() ); ?>/wp-content/uploads/2026/06/BTG_EXTERIOR_031.jpg" alt="Community exterior view" loading="lazy">
            </div>
        </div>
    </div>
</section>

<!-- Map Section -->
<section class="btg-section">
    <div class="btg-container">
        <h2 class="btg-section-title">Find Us</h2>
        <div class="contact-map-section">
            <iframe src="https://maps.google.com/maps?q=9990+Pineapple+Tree+Dr,+Boynton+Beach,+FL+33436&t=&z=15&ie=UTF8&iwloc=&output=embed"5e0!3m2!1sen!2sus!4v1700000000000!5m2!1sen!2sus" allowfullscreen="" loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe>
        </div>
    </div>
</section>

<?php get_footer(); ?>
