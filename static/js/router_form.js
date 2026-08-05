function toggleAuthFields() {
  const form = document.getElementById('router-form');
  const m = document.getElementById('auth_method').value;
  const isEdit = form.dataset.isEdit === 'true';
  const passwordField = document.getElementById('password-field');
  const keyField = document.getElementById('key-field');
  const passwordInput = document.getElementById('password');
  const sshKeyInput = document.getElementById('ssh_key');

  passwordField.classList.toggle('hidden', m === 'key');
  keyField.classList.toggle('hidden', m === 'password');

  if (isEdit) {
    passwordInput.removeAttribute('required');
    sshKeyInput.removeAttribute('required');
    return;
  }

  if (m === 'key') {
    passwordInput.removeAttribute('required');
    sshKeyInput.setAttribute('required', 'required');
  } else {
    passwordInput.setAttribute('required', 'required');
    sshKeyInput.removeAttribute('required');
  }
}

function testFromForm() {
  const btn = document.getElementById('test-btn');
  const f = document.getElementById('router-form');
  const data = {
    host: f.host.value.trim(),
    port: f.port.value,
    username: f.username.value.trim(),
    auth_method: f.auth_method.value,
    password: f.password.value,
    ssh_key: f.ssh_key.value,
    csrf_token: document.querySelector('meta[name="csrf-token"]').content,
  };

  btn.disabled = true;
  btn.textContent = 'Testing…';

  fetch(f.dataset.apiTestUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': data.csrf_token,
    },
    body: JSON.stringify(data),
  })
    .then((r) => r.json())
    .then((r) => {
      if (r.success) {
        showSuccess('Connection successful!\n' + JSON.stringify(r.info || {}, null, 2), 'Connection successful');
      } else {
        showError('Error ' + r.message);
      }
    })
    .catch((e) => showError('Error: ' + e))
    .finally(() => {
      btn.disabled = false;
      btn.textContent = 'Test Connection';
    });
}

function initRouterForm() {
  const authMethod = document.getElementById('auth_method');
  const testBtn = document.getElementById('test-btn');
  if (!authMethod || !testBtn) return;

  authMethod.addEventListener('change', toggleAuthFields);
  testBtn.addEventListener('click', testFromForm);

  toggleAuthFields();
}

document.addEventListener('DOMContentLoaded', initRouterForm);
