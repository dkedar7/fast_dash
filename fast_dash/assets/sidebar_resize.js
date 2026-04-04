// Sidebar resize functionality
(function() {
    'use strict';

    // Wait for DOM to be ready
    function initSidebarResize() {
        const resizeHandle = document.getElementById('sidebar-resize-handle');
        const sidebarWrapper = document.getElementById('input-group-wrapper');

        if (!resizeHandle || !sidebarWrapper) {
            // Elements not ready yet, try again
            setTimeout(initSidebarResize, 100);
            return;
        }

        let isResizing = false;
        let startX = 0;
        let startWidth = 0;

        // Load saved width from localStorage
        const savedWidth = localStorage.getItem('sidebar-width');
        if (savedWidth) {
            sidebarWrapper.style.width = savedWidth;
        }

        resizeHandle.addEventListener('mousedown', function(e) {
            // Only allow resizing if sidebar is visible
            const computedStyle = window.getComputedStyle(sidebarWrapper);
            if (computedStyle.display === 'none') {
                return;
            }

            isResizing = true;
            startX = e.clientX;
            startWidth = sidebarWrapper.offsetWidth;

            // Add resizing class for cursor
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';

            e.preventDefault();
        });

        document.addEventListener('mousemove', function(e) {
            if (!isResizing) return;

            const deltaX = e.clientX - startX;
            const newWidth = startWidth + deltaX;

            // Get viewport width and calculate max width (50%)
            const viewportWidth = window.innerWidth;
            const maxWidth = viewportWidth * 0.5;
            const minWidth = 150;

            // Constrain width between min and max
            if (newWidth >= minWidth && newWidth <= maxWidth) {
                // Convert to percentage for responsiveness
                const widthPercent = (newWidth / viewportWidth) * 100;
                sidebarWrapper.style.width = widthPercent + '%';
            } else if (newWidth < minWidth) {
                sidebarWrapper.style.width = minWidth + 'px';
            } else if (newWidth > maxWidth) {
                sidebarWrapper.style.width = '50%';
            }
        });

        document.addEventListener('mouseup', function() {
            if (isResizing) {
                isResizing = false;
                document.body.style.cursor = '';
                document.body.style.userSelect = '';

                // Save the width to localStorage
                localStorage.setItem('sidebar-width', sidebarWrapper.style.width);
            }
        });

        // Handle window resize to maintain max constraint
        let resizeTimeout;
        window.addEventListener('resize', function() {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(function() {
                const viewportWidth = window.innerWidth;
                const currentWidth = sidebarWrapper.offsetWidth;
                const maxWidth = viewportWidth * 0.5;

                if (currentWidth > maxWidth) {
                    sidebarWrapper.style.width = '50%';
                    localStorage.setItem('sidebar-width', '50%');
                }
            }, 250);
        });
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSidebarResize);
    } else {
        initSidebarResize();
    }

    // Also listen for clientside callbacks that might update the DOM
    if (window.dash_clientside) {
        window.dash_clientside = window.dash_clientside || {};
    }

    // Re-initialize after Dash updates (for dynamic content)
    const observer = new MutationObserver(function(mutations) {
        const hasResizeHandle = document.getElementById('sidebar-resize-handle');
        if (hasResizeHandle && !hasResizeHandle.dataset.initialized) {
            hasResizeHandle.dataset.initialized = 'true';
            initSidebarResize();
        }
    });

    // Start observing the document body for changes
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
})();
