function initSimpleFormValidation(formSelector) {
  const form = document.querySelector(formSelector);
  if (!form) return;

  function markInvalid(field) {
    field.classList.add("is-invalid");
    field.setAttribute("aria-invalid", "true");
  }

  function clearInvalid(field) {
    field.classList.remove("is-invalid");
    field.removeAttribute("aria-invalid");
    const feedback = field.nextElementSibling;
    if (feedback && feedback.classList.contains("invalid-feedback")) {
      feedback.classList.remove("d-block");
    }
  }

  function showFieldError(field, message) {
    markInvalid(field);
    let feedback = field.nextElementSibling;
    if (!feedback || !feedback.classList.contains("invalid-feedback")) {
      feedback = document.createElement("div");
      feedback.className = "invalid-feedback";
      field.insertAdjacentElement("afterend", feedback);
    }
    feedback.textContent = message;
    feedback.classList.add("d-block");
  }

  function getFieldError(field, invalidFile, invalidCheckbox, invalidValue) {
    if (invalidFile) return "Please select a file for this required document.";
    if (invalidCheckbox) return "Please check this box to continue.";
    if (invalidValue) {
      const label = field.labels && field.labels.length
        ? field.labels[0].textContent.trim().replace(/\s*\*\s*$/, "")
        : "";
      return `${label || "This field"} is required.`;
    }
    return field.validationMessage || "Please enter a valid value.";
  }

  form.querySelectorAll("input, select, textarea").forEach((field) => {
    field.addEventListener("input", () => clearInvalid(field));
    field.addEventListener("change", () => clearInvalid(field));
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

    form.querySelectorAll("input, select, textarea").forEach((field) => {
      const invalidFile = field.matches("input[type=file][data-required=true]") && !field.files.length;
      const invalidCheckbox = field.type === "checkbox" && field.required && !field.checked;
      const invalidValue = field.required && !field.value.trim();
      const invalidFormat = field.willValidate && !field.checkValidity();

      if (invalidFile || invalidCheckbox || invalidValue || invalidFormat) {
        showFieldError(field, getFieldError(field, invalidFile, invalidCheckbox, invalidValue));
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