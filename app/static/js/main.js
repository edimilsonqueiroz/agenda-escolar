(() => {
  /* ---- Theme ---- */
  const root = document.documentElement;
  const stored = localStorage.getItem('ae-theme') || 'light';
  root.dataset.theme = stored;

  document.getElementById('theme-toggle')?.addEventListener('click', () => {
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    localStorage.setItem('ae-theme', next);
  });

  /* ---- Sidebar collapse (desktop) ---- */
  if (localStorage.getItem('ae-sidebar-collapsed') === '1') {
    document.body.classList.add('sidebar-collapsed');
  }

  document.getElementById('sidebar-collapse-btn')?.addEventListener('click', () => {
    document.body.classList.toggle('sidebar-collapsed');
    const collapsed = document.body.classList.contains('sidebar-collapsed');
    localStorage.setItem('ae-sidebar-collapsed', collapsed ? '1' : '0');
  });

  /* ---- Hamburger (mobile) ---- */
  document.getElementById('hamburger')?.addEventListener('click', () => {
    document.body.classList.toggle('sidebar-open');
  });

  document.getElementById('sidebar-overlay')?.addEventListener('click', () => {
    document.body.classList.remove('sidebar-open');
  });

  /* ---- Chat badge (atualizado via dashboard.js) ---- */
  const chatBadge = document.getElementById('chat-notification-badge');

  window.unreadMessages = 0;
  window.addUnreadMessage = (shouldShow) => {
    if (shouldShow !== false) {
      window.unreadMessages++;
      if (chatBadge) {
        chatBadge.textContent = window.unreadMessages;
        chatBadge.style.display = 'flex';
      }
    }
  };

  window.clearUnreadMessages = () => {
    window.unreadMessages = 0;
    if (chatBadge) {
      chatBadge.style.display = 'none';
    }
  };

  /* ---- Logout Confirmation Modal ---- */
  const logoutBtn = document.getElementById('logout-btn');
  const logoutModal = document.getElementById('logout-modal');
  const logoutCancelBtn = document.getElementById('logout-cancel-btn');
  const logoutConfirmBtn = document.getElementById('logout-confirm-btn');
  const logoutForm = document.getElementById('logout-form');

  if (logoutBtn && logoutModal) {
    logoutBtn.addEventListener('click', () => {
      logoutModal.hidden = false;
    });
  }

  if (logoutCancelBtn && logoutModal) {
    logoutCancelBtn.addEventListener('click', () => {
      logoutModal.hidden = true;
    });
  }

  if (logoutConfirmBtn && logoutForm) {
    logoutConfirmBtn.addEventListener('click', () => {
      logoutForm.submit();
    });
  }

  if (logoutModal) {
    logoutModal.addEventListener('click', (e) => {
      if (e.target === logoutModal) {
        logoutModal.hidden = true;
      }
    });
  }
})();

