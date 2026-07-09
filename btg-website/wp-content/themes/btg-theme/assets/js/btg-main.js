/**
 * Bent Tree Gardens West — Main Theme JavaScript
 */
(function() {
    'use strict';

    // Mobile navigation toggle
    document.addEventListener('DOMContentLoaded', function() {
        var navToggle = document.querySelector('.btg-nav-toggle');
        var navMenu = document.querySelector('.btg-nav ul');

        if (navToggle && navMenu) {
            navToggle.addEventListener('click', function(e) {
                e.preventDefault();
                navMenu.classList.toggle('active');
            });

            // Close menu when clicking outside
            document.addEventListener('click', function(e) {
                if (!e.target.closest('.btg-nav')) {
                    navMenu.classList.remove('active');
                }
            });
        }

        // Smooth scroll for anchor links
        document.querySelectorAll('a[href^="#"]').forEach(function(anchor) {
            anchor.addEventListener('click', function(e) {
                var target = document.querySelector(this.getAttribute('href'));
                if (target) {
                    e.preventDefault();
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            });
        });

        // Header shadow on scroll
        var header = document.querySelector('.btg-header');
        if (header) {
            window.addEventListener('scroll', function() {
                if (window.scrollY > 10) {
                    header.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
                } else {
                    header.style.boxShadow = '0 1px 3px rgba(0,0,0,0.08)';
                }
            });
        }

        // Gallery lightbox (simple)
        document.querySelectorAll('.btg-gallery-item').forEach(function(item) {
            item.addEventListener('click', function() {
                var img = this.querySelector('img');
                if (!img) return;

                var overlay = document.createElement('div');
                overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.9);z-index:9999;display:flex;align-items:center;justify-content:center;cursor:pointer;';

                var fullImg = document.createElement('img');
                fullImg.src = img.src.replace(/-\d+x\d+/, ''); // Try full-size
                fullImg.style.cssText = 'max-width:90%;max-height:90%;border-radius:8px;';

                overlay.appendChild(fullImg);
                document.body.appendChild(overlay);

                overlay.addEventListener('click', function() {
                    document.body.removeChild(overlay);
                });

                document.addEventListener('keydown', function handler(e) {
                    if (e.key === 'Escape') {
                        if (document.body.contains(overlay)) {
                            document.body.removeChild(overlay);
                        }
                        document.removeEventListener('keydown', handler);
                    }
                });
            });
        });
    });
})();
