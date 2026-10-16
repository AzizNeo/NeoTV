/**
 * Where the admin panel lives — one constant for the route (manifest) and the tab links (page).
 *
 * Links are absolute on purpose: under React Router v7 a relative link inside a splat route
 * (`/admin/*`) resolves from the *full* current URL, so `to="catalog"` on /admin/overview led to
 * /admin/overview/catalog, and every further click nested deeper.
 */
export const ADMIN_BASE = '/admin';
export const adminPath = (section) => `${ADMIN_BASE}/${section}`;
