// Tailwind scans these files for class names; rebuild with `npm run build:css` after changing templates.
module.exports = {
  content: [
    './orders/templates/**/*.html',
    './panel/templates/**/*.html',
    './static/js/**/*.js',
    './orders/**/*.py',
    './panel/**/*.py',
  ],
  theme: { extend: {} },
  plugins: [],
};
