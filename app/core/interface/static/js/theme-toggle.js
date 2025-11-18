/**
 * Theme Toggle - Light/Dark Mode Switcher
 */
(function() {
    'use strict';
    
    const html = document.documentElement;
    const themeToggle = document.getElementById('theme-toggle');
    const themeIcon = document.getElementById('theme-icon');
    
    // Load saved theme or default to light
    const savedTheme = localStorage.getItem('gridline-theme') || 'light';
    html.setAttribute('data-theme', savedTheme);
    updateIcon(savedTheme);
    
    // Toggle theme on button click
    if (themeToggle) {
        themeToggle.addEventListener('click', function() {
            const currentTheme = html.getAttribute('data-theme');
            const newTheme = currentTheme === 'light' ? 'dark' : 'light';
            
            // Update theme
            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('gridline-theme', newTheme);
            updateIcon(newTheme);
            
            console.log(`🎨 Theme switched to: ${newTheme}`);
        });
    }
    
    /**
     * Update icon based on theme
     */
    function updateIcon(theme) {
        if (themeIcon) {
            if (theme === 'dark') {
                themeIcon.className = 'bi bi-sun-fill';
            } else {
                themeIcon.className = 'bi bi-moon-stars-fill';
            }
        }
    }
})();