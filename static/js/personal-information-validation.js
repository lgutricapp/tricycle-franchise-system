function initPersonalInformationValidation(formSelector) {
  const form = document.querySelector(formSelector);
  if (!form) return;

  form.querySelectorAll("[data-name-input]").forEach((field) => {
    field.addEventListener("input", () => {
      field.value = field.value.replace(/[^\p{L} ]/gu, "");
    });
  });

  form.querySelectorAll("[data-contact-number]").forEach((field) => {
    field.addEventListener("input", () => {
      field.value = field.value.replace(/[^0-9]/g, "").slice(0, 11);
    });
  });
}
