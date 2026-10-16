function initSimpleFormValidation(formSelector) {
  const form = document.querySelector(formSelector);
  if (!form) return;

  function markInvalid(field) {
    field.classList.add("is-invalid");
  }

  function clearInvalid(field) {
    field.classList.remove("is-invalid");
  }

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

  form.addEventListener("submit", (event) => {
    let firstInvalid = null;

    form.querySelectorAll("input[required], select[required], textarea[required]").forEach((field) => {
      if (!field.value.trim()) {
        markInvalid(field);
        if (!firstInvalid) firstInvalid = field;
      } else {
        clearInvalid(field);
      }
    });

    form.querySelectorAll("input[type=file][data-required=true]").forEach((field) => {
      if (!field.files.length) {
        markInvalid(field);
        if (!firstInvalid) firstInvalid = field;
      } else {
        clearInvalid(field);
      }
    });

    if (firstInvalid) {
      event.preventDefault();
      firstInvalid.focus();
    }
  });
}