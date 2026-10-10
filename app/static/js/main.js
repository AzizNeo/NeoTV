async function toggleFavorite(e, id) {
    e.preventDefault();
    e.stopPropagation(); // Prevent link click
    try {
        const res = await fetch(`/api/toggle_favorite/${id}`, { method: 'POST' });
        const data = await res.json();

        const btn = e.target;
        if (data.status === 'added') {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    } catch (err) {
        console.error('Error toggling favorite:', err);
    }
}
