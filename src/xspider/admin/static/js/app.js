/**
 * xspider Admin JavaScript
 */

// API Helper
const api = {
    async get(url) {
        const response = await fetch(url);
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Request failed');
        }
        return response.json();
    },

    async post(url, data) {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Request failed');
        }
        return response.json();
    },

    async delete(url) {
        const response = await fetch(url, { method: 'DELETE' });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Request failed');
        }
        return true;
    }
};

// Logout function
async function logout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
    } catch (e) {
        // Ignore errors
    }
    window.location.href = '/login';
}

// Format numbers
function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}

// Format date
function formatDate(dateStr) {
    return new Date(dateStr).toLocaleString();
}

// Format relative time
function formatTimeAgo(date) {
    const seconds = Math.floor((new Date() - date) / 1000);

    if (seconds < 60) return 'just now';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
    if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago';
    return Math.floor(seconds / 86400) + 'd ago';
}

// Show toast notification
function showToast(message, type = 'info') {
    // Create toast container if not exists
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'position-fixed bottom-0 end-0 p-3';
        container.style.zIndex = '1100';
        document.body.appendChild(container);
    }

    const toastId = 'toast-' + Date.now();
    const bgClass = type === 'error' ? 'bg-danger' :
                   type === 'success' ? 'bg-success' :
                   type === 'warning' ? 'bg-warning' : 'bg-info';

    const toastHtml = `
        <div id="${toastId}" class="toast align-items-center text-white ${bgClass}" role="alert">
            <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>
    `;

    container.insertAdjacentHTML('beforeend', toastHtml);

    const toastEl = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastEl, { autohide: true, delay: 5000 });
    toast.show();

    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
}

// Confirm dialog
function confirmAction(message) {
    return confirm(message);
}

// Copy to clipboard
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('Copied to clipboard', 'success');
    } catch (err) {
        showToast('Failed to copy', 'error');
    }
}

// Update credit balance in navbar
async function updateNavbarCredits() {
    try {
        const response = await fetch('/api/credits/balance');
        if (response.ok) {
            const data = await response.json();
            const balanceEl = document.getElementById('credit-balance');
            if (balanceEl) {
                balanceEl.textContent = data.balance;
            }
        }
    } catch (e) {
        // Ignore errors
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Update credits periodically
    setInterval(updateNavbarCredits, 60000);

    // Add active class to current nav item
    const currentPath = window.location.pathname;
    document.querySelectorAll('.navbar-nav .nav-link').forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });

    // Initialize Bootstrap tooltips
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    tooltipTriggerList.forEach(el => new bootstrap.Tooltip(el));
});

// Export for use in other scripts
window.xspider = {
    api,
    formatNumber,
    formatDate,
    formatTimeAgo,
    showToast,
    confirmAction,
    copyToClipboard,
    updateNavbarCredits
};
