const menuToggle = document.getElementById('menu-toggle');
const mobileDrawer = document.getElementById('mobile-drawer');

function setMenu(open) {
  if (!menuToggle || !mobileDrawer) return;
  menuToggle.classList.toggle('open', open);
  mobileDrawer.classList.toggle('open', open);
  menuToggle.setAttribute('aria-expanded', String(open));
  document.body.style.overflow = open ? 'hidden' : '';
}

if (menuToggle && mobileDrawer) {
  menuToggle.addEventListener('click', () => setMenu(!mobileDrawer.classList.contains('open')));
  mobileDrawer.querySelectorAll('a, button').forEach((element) => {
    element.addEventListener('click', () => setMenu(false));
  });
  window.addEventListener('resize', () => {
    if (window.innerWidth > 960) setMenu(false);
  });
}

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') setMenu(false);
});

const year = document.getElementById('copyright-year');
if (year) year.textContent = new Date().getFullYear();

function previewImage(input) {
  const area = input.closest('.upload-area');
  const preview = area?.querySelector('.upload-preview');
  const text = area?.querySelector('.upload-text');
  const icon = area?.querySelector('.upload-icon');
  if (!preview || !input.files?.[0]) return;
  const reader = new FileReader();
  reader.onload = (event) => {
    preview.src = event.target.result;
    preview.style.display = 'block';
    if (text) text.style.display = 'none';
    if (icon) icon.style.display = 'none';
  };
  reader.readAsDataURL(input.files[0]);
}

window.previewImage = previewImage;
