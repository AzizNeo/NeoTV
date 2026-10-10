document.addEventListener('DOMContentLoaded', () => {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', (e) => {
            // Optional: Add client-side validation here
            const password = form.querySelector('input[name="password"]');
            if (password && password.value.length < 4) {
                // e.preventDefault();
                // alert('Password must be at least 4 characters');
            }
        });
    });
});
