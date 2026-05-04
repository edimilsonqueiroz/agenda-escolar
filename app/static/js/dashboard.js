const appointmentSchedulerState = {
  weekOffset: 0,
  selectedPsychologistId: null,
  selectedStartTime: "",
};

async function fetchPsychologists() {
  const select = document.getElementById("psychologist-select");
  if (!select) return [];

  const response = await fetch("/api/psychologists", { credentials: "same-origin" });
  if (!response.ok) throw new Error("Erro ao carregar psicologos");
  const data = await response.json();

  select.innerHTML = '<option value="">Selecione o psicologo(a)</option>';
  data.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.name;
    select.appendChild(option);
  });

  return data;
}

function setAppointmentStartTime(value) {
  appointmentSchedulerState.selectedStartTime = value;
  const hidden = document.getElementById("appointment-start-time");
  if (hidden) hidden.value = value || "";
}

function renderWeekRange(weekStart, weekEnd) {
  const rangeEl = document.getElementById("appointment-week-range");
  if (!rangeEl) return;

  const formatDate = (iso) => {
    const [year, month, day] = iso.split("-");
    return `${day}/${month}/${year}`;
  };

  rangeEl.textContent = `${formatDate(weekStart)} a ${formatDate(weekEnd)}`;
}

function renderWeeklySlots(days) {
  const container = document.getElementById("appointment-weekly-slots");
  if (!container) return;

  container.innerHTML = "";

  let hasAnyAvailableSlot = false;
  let selectedStillAvailable = false;

  days.forEach((day) => {
    const col = document.createElement("div");
    col.className = "week-slot-day";

    const [year, month, dayNum] = day.date.split("-");

    const header = document.createElement("div");
    header.className = "week-slot-day-header";
    header.innerHTML = `<strong>${day.day_name}</strong><span>${dayNum}/${month}</span>`;
    col.appendChild(header);

    const list = document.createElement("div");
    list.className = "week-slot-list";

    if (day.slots.length === 0) {
      const empty = document.createElement("span");
      empty.className = "week-slot-none";
      empty.textContent = "Sem horarios";
      list.appendChild(empty);
    } else {
      day.slots.forEach((slot) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "week-slot-btn";
        button.textContent = slot.time;
        button.dataset.slotValue = slot.value;

        if (slot.reserved) {
          button.classList.add("week-slot-btn--reserved");
          button.disabled = true;
          button.title = "Horario ja reservado";
        } else {
          hasAnyAvailableSlot = true;

          if (slot.value === appointmentSchedulerState.selectedStartTime) {
            button.classList.add("week-slot-btn--active");
            selectedStillAvailable = true;
          }

          button.addEventListener("click", () => {
            document.querySelectorAll(".week-slot-btn").forEach((btn) => {
              btn.classList.remove("week-slot-btn--active");
            });
            button.classList.add("week-slot-btn--active");
            setAppointmentStartTime(slot.value);
          });
        }

        list.appendChild(button);
      });
    }

    col.appendChild(list);
    container.appendChild(col);
  });

  if (!hasAnyAvailableSlot || !selectedStillAvailable) {
    setAppointmentStartTime("");
  }
}

async function loadWeeklySlots() {
  const nav = document.getElementById("appointment-week-nav");
  const container = document.getElementById("appointment-weekly-slots");

  if (!container || !appointmentSchedulerState.selectedPsychologistId) {
    if (nav) nav.style.display = "none";
    return;
  }

  if (nav) nav.style.display = "flex";

  const response = await fetch(
    `/api/psychologists/${appointmentSchedulerState.selectedPsychologistId}/weekly-slots?week=${appointmentSchedulerState.weekOffset}`,
    { credentials: "same-origin" }
  );

  if (!response.ok) {
    container.innerHTML = '<div class="week-slot-empty">Nao foi possivel carregar os horarios.</div>';
    return;
  }

  const payload = await response.json();
  renderWeekRange(payload.week_start, payload.week_end);
  renderWeeklySlots(payload.days || []);
}

async function initializeAppointmentScheduler() {
  const psychologistSelect = document.getElementById("psychologist-select");
  if (!psychologistSelect) return;

  const container = document.getElementById("appointment-weekly-slots");
  const prevWeekBtn = document.getElementById("appointment-prev-week");
  const nextWeekBtn = document.getElementById("appointment-next-week");
  const form = psychologistSelect.closest("form");

  try {
    await fetchPsychologists();
  } catch (_err) {
    psychologistSelect.innerHTML = '<option value="">Erro ao carregar</option>';
    if (container) {
      container.innerHTML = '<div class="week-slot-empty">Nao foi possivel carregar psicologos.</div>';
    }
    return;
  }

  psychologistSelect.addEventListener("change", async () => {
    appointmentSchedulerState.selectedPsychologistId = psychologistSelect.value || null;
    appointmentSchedulerState.weekOffset = 0;
    setAppointmentStartTime("");

    if (!appointmentSchedulerState.selectedPsychologistId) {
      const nav = document.getElementById("appointment-week-nav");
      if (nav) nav.style.display = "none";
      if (container) {
        container.innerHTML = '<div class="week-slot-empty">Selecione a psicologa para carregar os horarios.</div>';
      }
      return;
    }

    await loadWeeklySlots();
  });

  prevWeekBtn?.addEventListener("click", async () => {
    appointmentSchedulerState.weekOffset -= 1;
    setAppointmentStartTime("");
    await loadWeeklySlots();
  });

  nextWeekBtn?.addEventListener("click", async () => {
    appointmentSchedulerState.weekOffset += 1;
    setAppointmentStartTime("");
    await loadWeeklySlots();
  });

  form?.addEventListener("submit", (event) => {
    if (!appointmentSchedulerState.selectedStartTime) {
      event.preventDefault();
      window.alert("Selecione um horario disponivel antes de agendar.");
    }
  });
}

// Rastrear conversas privadas e usuários
window.chatState = {
  onlineUsers: {},
  conversas: {}, // { userId: { name, lastMessage, timestamp } }
  currentMode: "group", // "group" ou "dm"
  currentDmRecipient: null,
  currentDmRoom: null,   // nome da sala DM ativa, ex: "dm_1_5"
  socket: null,
};

function renderOnlineUsers(users) {
  const container = document.getElementById("online-users");
  if (!container) return;

  window.chatState.onlineUsers = {};
  container.innerHTML = "";
  users.forEach((user) => {
    window.chatState.onlineUsers[user.id] = user;
    const li = document.createElement("li");
    li.dataset.userId = user.id;

    const avatarEl = document.createElement("span");
    avatarEl.className = "online-user-avatar";
    if (user.avatar) {
      avatarEl.innerHTML = `<img src="/static/uploads/avatars/${user.avatar}" alt="${user.name}" class="online-user-avatar__img">`;
    } else {
      avatarEl.textContent = (user.name || "?")[0].toUpperCase();
    }

    const nameEl = document.createElement("span");
    nameEl.textContent = `${user.name} (${user.role})`;

    li.appendChild(avatarEl);
    li.appendChild(nameEl);
    li.addEventListener("click", () => openDM(user));
    container.appendChild(li);
  });
}

function openDM(user) {
  const recipientId = user.id;
  const currentUserId = window.APP_CONTEXT?.user?.id;

  if (recipientId === currentUserId) return;

  // Calcular nome da sala igual ao servidor: dm_menor_maior
  const [u1, u2] = [currentUserId, recipientId].sort((a, b) => a - b);
  const dmRoom = `dm_${u1}_${u2}`;

  window.chatState.currentMode = "dm";
  window.chatState.currentDmRecipient = recipientId;
  window.chatState.currentDmRoom = dmRoom;
  document.getElementById("current-dm-recipient").value = recipientId;

  // Atualizar título
  document.getElementById("chat-title").textContent = `Chat com ${user.name}`;

  // Juntar sala privada
  if (window.chatState.socket) {
    window.chatState.socket.emit("chat:join_dm", { recipient_id: recipientId });
  }

  // Carregar histórico
  loadDMHistory(recipientId);

  // Mostrar botão de voltar (só existe na página de chat)
  const backBtn = document.getElementById("chat-back-btn");
  if (backBtn) backBtn.style.display = "inline-flex";

  // Marcar como ativo na lista
  document.querySelectorAll(".dm-list li").forEach((li) => {
    li.classList.remove("dm-item--active");
  });
  const activeLi = document.querySelector(`.dm-list li[data-user-id="${recipientId}"]`);
  if (activeLi) {
    activeLi.classList.add("dm-item--active");
  }
}

function switchToGroupChat() {
  window.chatState.currentMode = "group";
  window.chatState.currentDmRecipient = null;
  window.chatState.currentDmRoom = null;
  document.getElementById("current-dm-recipient").value = "";
  document.getElementById("chat-title").textContent = "Chat ao Vivo";

  // Carregar histórico do chat geral
  loadGroupHistory();

  document.querySelectorAll(".dm-list li").forEach((li) => {
    li.classList.remove("dm-item--active");
  });
}

function addToConversas(userId, userName, messagePreview) {
  if (!window.chatState.conversas[userId]) {
    window.chatState.conversas[userId] = {
      id: userId,
      name: userName,
      lastMessage: messagePreview,
      timestamp: Date.now(),
    };
  } else {
    window.chatState.conversas[userId].lastMessage = messagePreview;
    window.chatState.conversas[userId].timestamp = Date.now();
  }
  renderConversas();
}

function renderConversas() {
  const container = document.getElementById("dm-list");
  if (!container) return;

  const conversas = Object.values(window.chatState.conversas);
  conversas.sort((a, b) => b.timestamp - a.timestamp);

  container.innerHTML = "";
  conversas.forEach((conv) => {
    const li = document.createElement("li");
    li.dataset.userId = conv.id;
    li.className = window.chatState.currentDmRecipient === conv.id ? "dm-item--active" : "";
    li.innerHTML = `
      <div class="dm-item-name">${conv.name}</div>
      <div class="dm-item-preview">${conv.lastMessage}</div>
    `;
    li.addEventListener("click", () => {
      const user = window.chatState.onlineUsers[conv.id];
      if (user) {
        openDM(user);
      }
    });
    container.appendChild(li);
  });
}

function appendMessage(message) {
  const messages = document.getElementById("chat-messages");
  if (!messages) return;

  // Evitar mensagem duplicada (pode ocorrer se o servidor emitir para sala e para sender)
  if (message.id && messages.querySelector(`[data-msg-id="${message.id}"]`)) return;

  const currentUserId = window.APP_CONTEXT?.user?.id;
  const isMine = String(message.sender_id) === String(currentUserId);

  const row = document.createElement("div");
  row.className = `chat-row ${isMine ? "chat-row--mine" : "chat-row--theirs"}`;
  if (message.id) row.dataset.msgId = message.id;

  // Avatar do remetente (só mostra para mensagens de outros)
  if (!isMine) {
    const avatarEl = document.createElement("div");
    avatarEl.className = "chat-row-avatar";
    if (message.avatar) {
      const img = document.createElement("img");
      img.src = `/static/uploads/avatars/${message.avatar}`;
      img.alt = message.sender;
      img.className = "chat-row-avatar__img";
      avatarEl.appendChild(img);
    } else {
      avatarEl.textContent = (message.sender || "?")[0].toUpperCase();
    }
    row.appendChild(avatarEl);
  }

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";

  const date = new Date(message.created_at);
  const time = date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

  if (!isMine) {
    const name = document.createElement("span");
    name.className = "chat-bubble__name";
    name.textContent = message.sender;
    bubble.appendChild(name);
  }

  const text = document.createElement("p");
  text.className = "chat-bubble__text";
  text.textContent = message.content;
  bubble.appendChild(text);

  const footer = document.createElement("span");
  footer.className = "chat-bubble__footer";
  footer.innerHTML = `${time}${isMine ? ' <span class="chat-check">&#10003;&#10003;</span>' : ""}`;
  bubble.appendChild(footer);

  row.appendChild(bubble);
  messages.appendChild(row);
  messages.scrollTop = messages.scrollHeight;

  // Se não é minha mensagem, adicionar às conversas
  if (!isMine && window.chatState.currentMode === "dm") {
    addToConversas(message.sender_id, message.sender, message.content.substring(0, 40));
  }
}

async function loadGroupHistory() {
  const response = await fetch("/api/chat/messages?room=Geral", { credentials: "same-origin" });
  if (!response.ok) return;
  const history = await response.json();

  document.getElementById("chat-messages").innerHTML = "";
  history.forEach(appendMessage);
}

async function loadDMHistory(recipientId) {
  const response = await fetch(`/api/chat/messages?recipient_id=${recipientId}`, {
    credentials: "same-origin",
  });
  if (!response.ok) return;
  const history = await response.json();

  document.getElementById("chat-messages").innerHTML = "";
  history.forEach(appendMessage);
}

function startChat() {
  // O socket deve conectar em TODAS as páginas:
  // - aparece como online para outros usuários
  // - recebe badge de notificação de novas mensagens
  
  // Verifica se socket.io foi carregado
  if (typeof io === "undefined") {
    console.error("socket.io não foi carregado. Verifique a URL /socket.io/socket.io.js");
    return;
  }

  const socket = io({ transports: ["polling", "websocket"] });
  window.chatState.socket = socket;

  socket.on("presence:update", (payload) => {
    renderOnlineUsers(payload.online || []);
  });

  socket.on("chat:new", (payload) => {
    const onChatPage = !!document.getElementById("chat-messages");

    // Mensagem do chat geral
    if (payload.room === "Geral") {
      if (window.chatState.currentMode === "group" && onChatPage) {
        appendMessage(payload);
      } else {
        if (window.addUnreadMessage) window.addUnreadMessage(true);
      }
    }
    // Mensagem privada (usuário está na sala DM porque a abriu)
    else if (payload.room.startsWith("dm_")) {
      const isCurrentDM = window.chatState.currentMode === "dm" &&
        window.chatState.currentDmRoom === payload.room;

      if (isCurrentDM && onChatPage) {
        appendMessage(payload);
      } else {
        if (window.addUnreadMessage) window.addUnreadMessage(true);
      }

      // Atualizar painel de conversas: descobrir o ID do outro usuário
      const currentUserId = window.APP_CONTEXT?.user?.id;
      const parts = payload.room.split("_");
      const userId1 = parseInt(parts[1]);
      const userId2 = parseInt(parts[2]);
      const otherUserId = userId1 === currentUserId ? userId2 : userId1;
      addToConversas(otherUserId, payload.sender_id === currentUserId ? (window.chatState.onlineUsers[otherUserId]?.name || payload.sender) : payload.sender, payload.content.substring(0, 40));
    }
  });

  // Notificação DM via sala pessoal — para destinatário que não estava na sala DM
  socket.on("chat:dm_notify", (payload) => {
    const onChatPage = !!document.getElementById("chat-messages");
    const isCurrentDM = window.chatState.currentMode === "dm" &&
      window.chatState.currentDmRoom === payload.room;

    if (!(isCurrentDM && onChatPage)) {
      if (window.addUnreadMessage) window.addUnreadMessage(true);
    }

    const currentUserId = window.APP_CONTEXT?.user?.id;
    const parts = payload.room.split("_");
    const userId1 = parseInt(parts[1]);
    const userId2 = parseInt(parts[2]);
    const otherUserId = userId1 === currentUserId ? userId2 : userId1;
    addToConversas(otherUserId, payload.sender, payload.content.substring(0, 40));
  });

  // Handlers de UI do chat — só existem na página /chat
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  if (!form || !input) return;

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (!content) return;

    if (window.chatState.currentMode === "dm") {
      socket.emit("chat:send", {
        content,
        recipient_id: window.chatState.currentDmRecipient,
        csrf_token: window.APP_CONTEXT?.csrfToken,
      });
    } else {
      socket.emit("chat:send", {
        room: "Geral",
        content,
        csrf_token: window.APP_CONTEXT?.csrfToken,
      });
    }
    input.value = "";
  });

  // Setup dos tabs (só existem na página /chat)
  document.querySelectorAll(".chat-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll(".chat-tab-btn").forEach((b) => b.classList.remove("chat-tab-btn--active"));
      document.querySelectorAll(".chat-sidebar-panel").forEach((p) => p.classList.remove("chat-sidebar-panel--active"));

      btn.classList.add("chat-tab-btn--active");
      if (tab === "online") {
        document.getElementById("chat-online-panel").classList.add("chat-sidebar-panel--active");
        switchToGroupChat();
      } else {
        document.getElementById("chat-dms-panel").classList.add("chat-sidebar-panel--active");
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  // Psychologist scheduling — so existe no dashboard de aluno
  if (document.getElementById("psychologist-select")) {
    await initializeAppointmentScheduler();
  }

  const onChatPage = !!document.getElementById("chat-messages");

  // Aguarda socket.io estar disponível antes de iniciar (apenas para usuários autenticados)
  if (window.APP_CONTEXT?.user) {
    let attempts = 0;
    const waitForSocketIO = setInterval(() => {
      if (typeof io !== "undefined") {
        clearInterval(waitForSocketIO);
        startChat();
      } else if (attempts++ > 50) {  // 5 segundos de espera
        clearInterval(waitForSocketIO);
        console.warn("socket.io não ficou disponível após 5 segundos");
      }
    }, 100);
  }

  // Carrega histórico apenas na página de chat
  if (onChatPage) {
    await loadGroupHistory();
    // Limpar badge ao entrar na página de chat
    if (window.clearUnreadMessages) window.clearUnreadMessages();

    // Botão "Voltar ao geral"
    const backBtn = document.getElementById("chat-back-btn");
    if (backBtn) {
      backBtn.addEventListener("click", () => {
        switchToGroupChat();
        backBtn.style.display = "none";
      });
    }
  }
});
