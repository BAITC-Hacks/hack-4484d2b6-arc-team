/* Each page owns its lock; finishing one request cannot unlock another page. */
(() => {
  "use strict";
  const owners = new Set();
  function setBusy(owner, busy) {
    if (busy) owners.add(owner); else owners.delete(owner);
    const locked = owners.size > 0;
    const role = document.querySelector("#demo-profile");
    if (role) role.disabled = locked;
    document.querySelectorAll("#builder-switch-business, #business-switch-role, #proposal-switch-role, #team-switch")
      .forEach(button => { button.disabled = locked; });
  }
  window.SanaRole = Object.freeze({ setBusy, isBusy: () => owners.size > 0 });
})();
