const API = {
  pdgroups: "/api/pdgroups",
  contact: "/api/contact",
  authMe: "/api/auth/me",
};

function isEnglish() {
  return document.body.classList.contains("lang-en");
}

function text(th, en) {
  return isEnglish() ? en : th;
}

function showMessage(message) {
  alert(message);
}

function setAuthNav(isAuthenticated) {
  const dashboardLink = document.getElementById("dashboard-link");
  const loginLink = document.getElementById("login-link");
  const logoutLink = document.getElementById("logout-link");

  if (dashboardLink) dashboardLink.hidden = !isAuthenticated;
  if (loginLink) loginLink.hidden = isAuthenticated;
  if (logoutLink) logoutLink.hidden = !isAuthenticated;
}

async function updateAuthNav() {
  try {
    const response = await fetch(API.authMe, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    if (!response.ok) {
      throw new Error(`Auth status failed: ${response.status}`);
    }

    const data = await response.json();
    setAuthNav(Boolean(data.authenticated));
  } catch (error) {
    console.error(error);
    setAuthNav(false);
  }
}

function switchTab(tabId, button) {
  document.querySelectorAll(".prod-section").forEach((section) => {
    section.classList.remove("active");
  });
  document.querySelectorAll(".prod-tab").forEach((tab) => {
    tab.classList.remove("active");
  });

  const panel = document.getElementById(`tab-${tabId}`);
  if (panel) {
    panel.classList.add("active");
  }
  button.classList.add("active");
}

async function loadPdGroups() {
  const select = document.getElementById("pdgroup_id");
  if (!select) {
    return;
  }

  select.disabled = true;

  try {
    const response = await fetch(API.pdgroups, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`Unable to load product groups: ${response.status}`);
    }

    const groups = await response.json();
    const placeholder = select.querySelector('option[value=""]')?.textContent || "-- Select --";
    select.replaceChildren(new Option(placeholder, ""));

    groups.forEach((group) => {
      select.append(new Option(group.pdgroup_name || `Product group ${group.pdgroup_id}`, group.pdgroup_id));
    });
  } catch (error) {
    console.error(error);
    select.replaceChildren(
      new Option(text("ไม่สามารถโหลดประเภทสินค้าได้", "Unable to load product groups"), "")
    );
  } finally {
    select.disabled = false;
  }
}

function buildContactPayload(form) {
  const formData = new FormData(form);
  const payload = {
    person_name: (formData.get("person_name") || "").trim(),
    org_name: (formData.get("org_name") || "").trim() || null,
    tel: (formData.get("tel") || "").trim(),
    email: (formData.get("email") || "").trim() || null,
    pdgroup_id: formData.get("pdgroup_id") ? Number(formData.get("pdgroup_id")) : null,
    req_size: (formData.get("req_size") || "").trim() || null,
    address_send: (formData.get("address_send") || "").trim() || null,
    detail: (formData.get("detail") || "").trim() || null,
  };

  if (!payload.person_name || !payload.tel) {
    throw new Error(text("กรุณากรอกชื่อและเบอร์โทรศัพท์", "Please fill in name and phone."));
  }

  return payload;
}

async function submitContactForm(event) {
  event.preventDefault();

  const form = event.currentTarget;
  const submitButton = document.getElementById("contact-submit");

  let payload;
  try {
    payload = buildContactPayload(form);
  } catch (error) {
    showMessage(error.message);
    return;
  }

  submitButton.disabled = true;

  try {
    const response = await fetch(API.contact, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Contact request failed: ${response.status}`);
    }

    document.getElementById("form-area").style.display = "none";
    document.getElementById("success-msg").style.display = "block";
  } catch (error) {
    console.error(error);
    showMessage(text("ส่งคำขอไม่สำเร็จ กรุณาลองใหม่อีกครั้ง", "Unable to submit request. Please try again."));
  } finally {
    submitButton.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("lang-toggle")?.addEventListener("click", () => {
    document.body.classList.toggle("lang-en");
  });

  document.querySelectorAll(".prod-tab[data-tab]").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab, button));
  });

  document.getElementById("form-area")?.addEventListener("submit", submitContactForm);
  updateAuthNav();
  loadPdGroups();
});
