function initStepWizard(formSelector) {
  const form = document.querySelector(formSelector);
  if (!form) return;

  const panels = Array.from(form.querySelectorAll(".form-step-panel"));
  const indicatorItems = Array.from(form.querySelectorAll(".step-indicator li"));
  let currentStep = 0;

  function showStep(index) {
    panels.forEach((panel, i) => panel.classList.toggle("is-active", i === index));
    indicatorItems.forEach((item, i) => {
      item.classList.toggle("is-active", i === index);
      item.classList.toggle("is-complete", i < index);
    });
    currentStep = index;
    window.scrollTo({ top: form.offsetTop - 20, behavior: "smooth" });
  }

  function markInvalid(field) {
    field.classList.add("is-invalid");
  }

  function clearInvalid(field) {
    field.classList.remove("is-invalid");
  }

  function validateStep(index) {
    const panel = panels[index];
    let firstInvalid = null;

    panel.querySelectorAll("input[required], select[required], textarea[required]").forEach((field) => {
      if (!field.value.trim()) {
        markInvalid(field);
        if (!firstInvalid) firstInvalid = field;
      } else {
        clearInvalid(field);
      }
    });

    panel.querySelectorAll("input[type=file][data-required=true]").forEach((field) => {
      if (!field.files.length) {
        markInvalid(field);
        if (!firstInvalid) firstInvalid = field;
      } else {
        clearInvalid(field);
      }
    });

    if (firstInvalid) {
      firstInvalid.focus();
      return false;
    }
    return true;
  }

  form.querySelectorAll(".btn-step-next").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (validateStep(currentStep)) {
        showStep(currentStep + 1);
      }
    });
  });

  form.querySelectorAll(".btn-step-back").forEach((btn) => {
    btn.addEventListener("click", () => showStep(currentStep - 1));
  });

  // Clear the invalid state on a field as soon as the person starts fixing it.
  form.querySelectorAll("input, select, textarea").forEach((field) => {
    field.addEventListener("input", () => clearInvalid(field));
  });

  // Show the chosen filename and highlight the row once a file is selected.
  form.querySelectorAll(".document-row input[type=file]").forEach((input) => {
    input.addEventListener("change", () => {
      const row = input.closest(".document-row");
      const nameEl = row.querySelector(".file-chosen-name");
      if (input.files.length) {
        nameEl.textContent = "Selected: " + input.files[0].name;
        nameEl.style.display = "block";
        row.classList.add("has-file");
        clearInvalid(input);
      } else {
        nameEl.style.display = "none";
        row.classList.remove("has-file");
      }
    });
  });

  // Validate every step on final submit, in case a person edits a later
  // step, goes back, and leaves an earlier one incomplete.
  form.addEventListener("submit", (event) => {
    for (let i = 0; i < panels.length; i++) {
      if (!validateStep(i)) {
        showStep(i);
        event.preventDefault();
        return;
      }
    }
  });

  showStep(0);
}